"""tm_manager.py 테스트

Time Machine 로컬 스냅샷 관리 모듈의 단위 테스트.
subprocess.run 호출은 모두 mock 처리하여 실제 tmutil/diskutil 실행을 방지한다.
"""

import subprocess
import unittest
from unittest.mock import MagicMock, patch, call

from app.tm_manager import (
    list_snapshots,
    delete_snapshot,
    delete_all_snapshots,
    get_snapshots_size,
    _format_display,
    _try_tmutil_size,
    _try_diskutil_snapshot_size,
    _get_root_apfs_disk,
    TMUTIL_TIMEOUT,
    OSASCRIPT_TIMEOUT,
)


# ============================================================
# 테스트 데이터 상수
# ============================================================

# tmutil listlocalsnapshots / 정상 출력 예시
TMUTIL_OUTPUT_NORMAL = """\
Snapshots for disk /:
com.apple.TimeMachine.2025-01-15-123456.local
com.apple.TimeMachine.2025-02-20-091500.local
com.apple.TimeMachine.2025-03-01-180030.local
"""

# 스냅샷 없는 경우
TMUTIL_OUTPUT_EMPTY = "Snapshots for disk /:\n"

# 크기 정보가 포함된 tmutil 출력
TMUTIL_OUTPUT_WITH_SIZE = """\
Snapshots for disk /:
com.apple.TimeMachine.2025-01-15-123456.local (2.5GB)
com.apple.TimeMachine.2025-02-20-091500.local (500MB)
"""

# diskutil info / 출력
DISKUTIL_INFO_OUTPUT = """\
   Device Identifier:         disk1s1
   Device Node:               /dev/disk1s1
   Whole:                     No
   Part of Whole:             disk1
"""

# diskutil apfs listSnapshots 출력
DISKUTIL_SNAPSHOTS_OUTPUT = """\
Snapshot Name:               com.apple.TimeMachine.2025-01-15-123456.local
Snapshot Disk Size:  1073741824 B (1.0 GB)
Snapshot Name:               com.apple.TimeMachine.2025-02-20-091500.local
Snapshot Disk Size:  536870912 B (512.0 MB)
"""


def _make_completed_process(stdout="", stderr="", returncode=0):
    """subprocess.CompletedProcess mock 객체 생성 헬퍼"""
    proc = MagicMock(spec=subprocess.CompletedProcess)
    proc.stdout = stdout
    proc.stderr = stderr
    proc.returncode = returncode
    return proc


# ============================================================
# list_snapshots() 테스트
# ============================================================


class TestListSnapshots(unittest.TestCase):
    """list_snapshots() 함수 테스트"""

    @patch("app.tm_manager.subprocess.run")
    def test_parse_normal_output(self, mock_run):
        """정상 tmutil 출력에서 다수의 스냅샷을 올바르게 파싱"""
        mock_run.return_value = _make_completed_process(stdout=TMUTIL_OUTPUT_NORMAL)

        result = list_snapshots()

        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["date"], "2025-01-15-123456")
        self.assertEqual(result[1]["date"], "2025-02-20-091500")
        self.assertEqual(result[2]["date"], "2025-03-01-180030")

    @patch("app.tm_manager.subprocess.run")
    def test_empty_when_no_snapshots(self, mock_run):
        """스냅샷이 없을 때 빈 리스트 반환"""
        mock_run.return_value = _make_completed_process(stdout=TMUTIL_OUTPUT_EMPTY)

        result = list_snapshots()

        self.assertEqual(result, [])

    @patch("app.tm_manager.subprocess.run")
    def test_empty_on_timeout(self, mock_run):
        """subprocess.TimeoutExpired 발생 시 빈 리스트 반환"""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="tmutil", timeout=30)

        result = list_snapshots()

        self.assertEqual(result, [])

    @patch("app.tm_manager.subprocess.run")
    def test_empty_on_file_not_found(self, mock_run):
        """tmutil 바이너리가 없을 때(FileNotFoundError) 빈 리스트 반환"""
        mock_run.side_effect = FileNotFoundError("tmutil not found")

        result = list_snapshots()

        self.assertEqual(result, [])

    @patch("app.tm_manager.subprocess.run")
    def test_empty_on_os_error(self, mock_run):
        """OSError 발생 시 빈 리스트 반환"""
        mock_run.side_effect = OSError("permission denied")

        result = list_snapshots()

        self.assertEqual(result, [])

    @patch("app.tm_manager.subprocess.run")
    def test_extracts_correct_display_format(self, mock_run):
        """date와 display 필드가 올바른 형식으로 추출되는지 확인"""
        mock_run.return_value = _make_completed_process(stdout=TMUTIL_OUTPUT_NORMAL)

        result = list_snapshots()

        self.assertEqual(result[0]["display"], "2025-01-15 12:34:56")
        self.assertEqual(result[1]["display"], "2025-02-20 09:15:00")
        self.assertEqual(result[2]["display"], "2025-03-01 18:00:30")

    @patch("app.tm_manager.subprocess.run")
    def test_ignores_non_matching_lines(self, mock_run):
        """스냅샷 패턴에 맞지 않는 라인은 무시"""
        output = "Snapshots for disk /:\nrandom text\n\n"
        mock_run.return_value = _make_completed_process(stdout=output)

        result = list_snapshots()

        self.assertEqual(result, [])

    @patch("app.tm_manager.subprocess.run")
    def test_calls_tmutil_with_correct_args(self, mock_run):
        """tmutil을 올바른 인자로 호출하는지 확인"""
        mock_run.return_value = _make_completed_process(stdout="")

        list_snapshots()

        mock_run.assert_called_once_with(
            ["tmutil", "listlocalsnapshots", "/"],
            capture_output=True, text=True, timeout=TMUTIL_TIMEOUT,
        )


# ============================================================
# _format_display() 테스트
# ============================================================


class TestFormatDisplay(unittest.TestCase):
    """_format_display() 함수 테스트"""

    def test_normal_date_format(self):
        """정상 날짜 문자열 변환: YYYY-MM-DD-HHMMSS -> YYYY-MM-DD HH:MM:SS"""
        self.assertEqual(_format_display("2025-01-15-123456"), "2025-01-15 12:34:56")

    def test_midnight(self):
        """자정 시간 처리"""
        self.assertEqual(_format_display("2025-12-31-000000"), "2025-12-31 00:00:00")

    def test_end_of_day(self):
        """하루 마지막 시간 처리"""
        self.assertEqual(_format_display("2025-06-15-235959"), "2025-06-15 23:59:59")

    def test_short_input_returns_as_is(self):
        """길이가 17이 아닌 짧은 문자열은 그대로 반환"""
        self.assertEqual(_format_display("2025-01-15"), "2025-01-15")

    def test_long_input_returns_as_is(self):
        """길이가 17보다 긴 문자열은 그대로 반환"""
        self.assertEqual(
            _format_display("2025-01-15-1234567890"),
            "2025-01-15-1234567890",
        )

    def test_malformed_time_part_returns_as_is(self):
        """시간 부분이 6자리가 아닌 경우 그대로 반환 (길이 17이지만 구분자 위치 다름)"""
        # 길이 17이지만 time_part가 6자리가 아닌 경우
        malformed = "2025-01-15-12345X"  # 17자, time_part = "12345X" (6자)
        # 이 경우 len(time_part) == 6이므로 정상 처리된다
        # 실제 malformed case: date_raw[11:]의 길이가 6이 아닌 경우
        input_str = "2025-01-15X12345"  # 17자, date_part="2025-01-15", time_part="12345" (5자)
        self.assertEqual(_format_display(input_str), input_str)

    def test_empty_string_returns_as_is(self):
        """빈 문자열은 그대로 반환"""
        self.assertEqual(_format_display(""), "")


# ============================================================
# delete_snapshot() 테스트
# ============================================================


class TestDeleteSnapshot(unittest.TestCase):
    """delete_snapshot() 함수 테스트"""

    @patch("app.tm_manager.subprocess.run")
    def test_success_on_first_try_sudo_n(self, mock_run):
        """sudo -n으로 첫 시도에 성공"""
        mock_run.return_value = _make_completed_process(returncode=0)

        ok, msg = delete_snapshot("2025-01-15-123456")

        self.assertTrue(ok)
        self.assertIn("삭제 완료", msg)
        self.assertIn("2025-01-15-123456", msg)
        # sudo -n 호출만 1회 발생해야 함
        mock_run.assert_called_once()

    @patch("app.tm_manager.subprocess.run")
    def test_fallback_to_osascript_on_sudo_failure(self, mock_run):
        """sudo -n 실패 시 osascript로 fallback 성공"""
        # 첫 번째 호출(sudo -n): returncode != 0
        sudo_fail = _make_completed_process(returncode=1, stderr="sudo: a password is required")
        # 두 번째 호출(osascript): 성공
        osascript_ok = _make_completed_process(returncode=0)
        mock_run.side_effect = [sudo_fail, osascript_ok]

        ok, msg = delete_snapshot("2025-01-15-123456")

        self.assertTrue(ok)
        self.assertIn("삭제 완료", msg)
        self.assertEqual(mock_run.call_count, 2)

    @patch("app.tm_manager.subprocess.run")
    def test_failure_when_both_methods_fail(self, mock_run):
        """sudo -n과 osascript 모두 실패"""
        sudo_fail = _make_completed_process(returncode=1, stderr="sudo failed")
        osascript_fail = _make_completed_process(
            returncode=1, stderr="User cancelled"
        )
        mock_run.side_effect = [sudo_fail, osascript_fail]

        ok, msg = delete_snapshot("2025-01-15-123456")

        self.assertFalse(ok)
        self.assertIn("관리자 권한 인증 실패", msg)

    @patch("app.tm_manager.subprocess.run")
    def test_shlex_quote_in_osascript_command(self, mock_run):
        """osascript 호출 시 shlex.quote가 적용되어 안전한 명령이 생성되는지 확인"""
        import shlex

        sudo_fail = _make_completed_process(returncode=1)
        osascript_ok = _make_completed_process(returncode=0)
        mock_run.side_effect = [sudo_fail, osascript_ok]

        # 특수문자가 포함된 날짜 문자열로 테스트
        dangerous_input = "2025-01-15-123456; rm -rf /"
        delete_snapshot(dangerous_input)

        # osascript 호출의 인자 확인
        osascript_call = mock_run.call_args_list[1]
        script_arg = osascript_call[0][0][2]  # ["osascript", "-e", <script>]
        # shlex.quote가 적용되면 작은따옴표로 감싸져서 shell injection 방지
        safe_date = shlex.quote(dangerous_input)
        self.assertIn(safe_date, script_arg)

    @patch("app.tm_manager.subprocess.run")
    def test_timeout_on_sudo(self, mock_run):
        """sudo -n에서 타임아웃 발생"""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="sudo", timeout=30)

        ok, msg = delete_snapshot("2025-01-15-123456")

        self.assertFalse(ok)
        self.assertIn("시간 초과", msg)
        # 타임아웃이면 osascript 시도 없이 바로 반환
        mock_run.assert_called_once()

    @patch("app.tm_manager.subprocess.run")
    def test_timeout_on_osascript(self, mock_run):
        """osascript에서 타임아웃 발생"""
        sudo_fail = _make_completed_process(returncode=1)
        mock_run.side_effect = [
            sudo_fail,
            subprocess.TimeoutExpired(cmd="osascript", timeout=120),
        ]

        ok, msg = delete_snapshot("2025-01-15-123456")

        self.assertFalse(ok)
        self.assertIn("시간 초과", msg)
        self.assertIn("관리자 인증", msg)

    @patch("app.tm_manager.subprocess.run")
    def test_file_not_found_on_sudo(self, mock_run):
        """sudo 바이너리를 찾지 못할 때"""
        mock_run.side_effect = FileNotFoundError("sudo not found")

        ok, msg = delete_snapshot("2025-01-15-123456")

        self.assertFalse(ok)
        self.assertIn("실행 오류", msg)

    @patch("app.tm_manager.subprocess.run")
    def test_file_not_found_on_osascript(self, mock_run):
        """osascript 바이너리를 찾지 못할 때"""
        sudo_fail = _make_completed_process(returncode=1)
        mock_run.side_effect = [
            sudo_fail,
            FileNotFoundError("osascript not found"),
        ]

        ok, msg = delete_snapshot("2025-01-15-123456")

        self.assertFalse(ok)
        self.assertIn("실행 오류", msg)

    @patch("app.tm_manager.subprocess.run")
    def test_sudo_called_with_correct_args(self, mock_run):
        """sudo -n tmutil deletelocalsnapshots가 올바른 인자로 호출되는지 확인"""
        mock_run.return_value = _make_completed_process(returncode=0)

        delete_snapshot("2025-01-15-123456")

        mock_run.assert_called_once_with(
            ["sudo", "-n", "tmutil", "deletelocalsnapshots", "2025-01-15-123456"],
            capture_output=True, text=True, timeout=TMUTIL_TIMEOUT,
        )


# ============================================================
# delete_all_snapshots() 테스트
# ============================================================


class TestDeleteAllSnapshots(unittest.TestCase):
    """delete_all_snapshots() 함수 테스트"""

    @patch("app.tm_manager.delete_snapshot")
    @patch("app.tm_manager.list_snapshots")
    def test_deletes_multiple_and_counts(self, mock_list, mock_delete):
        """여러 스냅샷 삭제 시 성공/실패 카운트 정확성"""
        mock_list.return_value = [
            {"date": "2025-01-15-123456", "display": "2025-01-15 12:34:56"},
            {"date": "2025-02-20-091500", "display": "2025-02-20 09:15:00"},
            {"date": "2025-03-01-180030", "display": "2025-03-01 18:00:30"},
        ]
        # 첫 번째, 세 번째 성공 / 두 번째 실패
        mock_delete.side_effect = [
            (True, "삭제 완료"),
            (False, "실패"),
            (True, "삭제 완료"),
        ]

        success, fail, msg = delete_all_snapshots()

        self.assertEqual(success, 2)
        self.assertEqual(fail, 1)
        self.assertIn("3개 중 2개 삭제 완료", msg)
        self.assertIn("1개 실패", msg)

    @patch("app.tm_manager.list_snapshots")
    def test_no_snapshots_returns_zero(self, mock_list):
        """스냅샷이 없을 때 (0, 0, 메시지) 반환"""
        mock_list.return_value = []

        success, fail, msg = delete_all_snapshots()

        self.assertEqual(success, 0)
        self.assertEqual(fail, 0)
        self.assertIn("삭제할 스냅샷이 없습니다", msg)

    @patch("app.tm_manager.delete_snapshot")
    @patch("app.tm_manager.list_snapshots")
    def test_all_success(self, mock_list, mock_delete):
        """모든 스냅샷 삭제 성공"""
        mock_list.return_value = [
            {"date": "2025-01-15-123456", "display": "2025-01-15 12:34:56"},
            {"date": "2025-02-20-091500", "display": "2025-02-20 09:15:00"},
        ]
        mock_delete.return_value = (True, "삭제 완료")

        success, fail, msg = delete_all_snapshots()

        self.assertEqual(success, 2)
        self.assertEqual(fail, 0)
        self.assertIn("2개 중 2개 삭제 완료", msg)
        self.assertNotIn("실패", msg)

    @patch("app.tm_manager.delete_snapshot")
    @patch("app.tm_manager.list_snapshots")
    def test_all_failure(self, mock_list, mock_delete):
        """모든 스냅샷 삭제 실패"""
        mock_list.return_value = [
            {"date": "2025-01-15-123456", "display": "2025-01-15 12:34:56"},
        ]
        mock_delete.return_value = (False, "실패")

        success, fail, msg = delete_all_snapshots()

        self.assertEqual(success, 0)
        self.assertEqual(fail, 1)
        self.assertIn("1개 실패", msg)

    @patch("app.tm_manager.delete_snapshot")
    @patch("app.tm_manager.list_snapshots")
    def test_calls_delete_for_each_snapshot(self, mock_list, mock_delete):
        """list_snapshots 결과의 각 스냅샷에 대해 delete_snapshot 호출 확인"""
        mock_list.return_value = [
            {"date": "2025-01-15-123456", "display": "2025-01-15 12:34:56"},
            {"date": "2025-02-20-091500", "display": "2025-02-20 09:15:00"},
        ]
        mock_delete.return_value = (True, "ok")

        delete_all_snapshots()

        mock_delete.assert_any_call("2025-01-15-123456")
        mock_delete.assert_any_call("2025-02-20-091500")
        self.assertEqual(mock_delete.call_count, 2)


# ============================================================
# get_snapshots_size() 테스트
# ============================================================


class TestGetSnapshotsSize(unittest.TestCase):
    """get_snapshots_size() 함수 테스트"""

    @patch("app.tm_manager._try_diskutil_snapshot_size")
    @patch("app.tm_manager._try_tmutil_size")
    def test_returns_na_when_no_size_info(self, mock_tmutil, mock_diskutil):
        """크기 정보를 얻을 수 없을 때 (0, "N/A") 반환"""
        mock_tmutil.return_value = 0
        mock_diskutil.return_value = 0

        size_bytes, size_str = get_snapshots_size()

        self.assertEqual(size_bytes, 0)
        self.assertEqual(size_str, "N/A")

    @patch("app.tm_manager._try_diskutil_snapshot_size")
    @patch("app.tm_manager._try_tmutil_size")
    def test_uses_tmutil_size_when_available(self, mock_tmutil, mock_diskutil):
        """tmutil에서 크기 정보를 얻을 수 있으면 해당 값 사용"""
        mock_tmutil.return_value = 2 * 1024**3  # 2GB
        mock_diskutil.return_value = 0  # 호출되지 않아야 함

        size_bytes, size_str = get_snapshots_size()

        self.assertEqual(size_bytes, 2 * 1024**3)
        self.assertIn("GB", size_str)
        # tmutil이 값을 반환하면 diskutil은 호출하지 않음
        mock_diskutil.assert_not_called()

    @patch("app.tm_manager._try_diskutil_snapshot_size")
    @patch("app.tm_manager._try_tmutil_size")
    def test_falls_back_to_diskutil(self, mock_tmutil, mock_diskutil):
        """tmutil에서 크기 정보가 없으면 diskutil로 fallback"""
        mock_tmutil.return_value = 0
        mock_diskutil.return_value = 500 * 1024**2  # 500MB

        size_bytes, size_str = get_snapshots_size()

        self.assertEqual(size_bytes, 500 * 1024**2)
        self.assertIn("MB", size_str)


# ============================================================
# _try_tmutil_size() 내부 헬퍼 테스트
# ============================================================


class TestTryTmutilSize(unittest.TestCase):
    """_try_tmutil_size() 함수 테스트"""

    @patch("app.tm_manager.subprocess.run")
    def test_parses_gb_size(self, mock_run):
        """GB 단위 크기 파싱"""
        mock_run.return_value = _make_completed_process(stdout=TMUTIL_OUTPUT_WITH_SIZE)

        result = _try_tmutil_size()

        # 2.5GB + 500MB
        expected = int(2.5 * 1024**3) + int(500 * 1024**2)
        self.assertEqual(result, expected)

    @patch("app.tm_manager.subprocess.run")
    def test_returns_zero_on_no_size_info(self, mock_run):
        """크기 정보가 없는 출력에서 0 반환"""
        mock_run.return_value = _make_completed_process(stdout=TMUTIL_OUTPUT_NORMAL)

        result = _try_tmutil_size()

        self.assertEqual(result, 0)

    @patch("app.tm_manager.subprocess.run")
    def test_returns_zero_on_timeout(self, mock_run):
        """타임아웃 시 0 반환"""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="tmutil", timeout=30)

        result = _try_tmutil_size()

        self.assertEqual(result, 0)

    @patch("app.tm_manager.subprocess.run")
    def test_returns_zero_on_file_not_found(self, mock_run):
        """FileNotFoundError 시 0 반환"""
        mock_run.side_effect = FileNotFoundError()

        result = _try_tmutil_size()

        self.assertEqual(result, 0)

    @patch("app.tm_manager.subprocess.run")
    def test_parses_multiple_units(self, mock_run):
        """다양한 단위(KB, MB, GB, TB) 파싱"""
        output = """\
com.apple.TimeMachine.2025-01-01-000000.local (100KB)
com.apple.TimeMachine.2025-01-02-000000.local (50MB)
com.apple.TimeMachine.2025-01-03-000000.local (1.5GB)
com.apple.TimeMachine.2025-01-04-000000.local (0.5TB)
"""
        mock_run.return_value = _make_completed_process(stdout=output)

        result = _try_tmutil_size()

        expected = (
            int(100 * 1024)
            + int(50 * 1024**2)
            + int(1.5 * 1024**3)
            + int(0.5 * 1024**4)
        )
        self.assertEqual(result, expected)


# ============================================================
# _try_diskutil_snapshot_size() 내부 헬퍼 테스트
# ============================================================


class TestTryDiskutilSnapshotSize(unittest.TestCase):
    """_try_diskutil_snapshot_size() 함수 테스트"""

    @patch("app.tm_manager.subprocess.run")
    @patch("app.tm_manager._get_root_apfs_disk")
    def test_parses_snapshot_sizes(self, mock_disk_id, mock_run):
        """diskutil 출력에서 스냅샷 크기 합산"""
        mock_disk_id.return_value = "disk1s1"
        mock_run.return_value = _make_completed_process(
            stdout=DISKUTIL_SNAPSHOTS_OUTPUT
        )

        result = _try_diskutil_snapshot_size()

        expected = 1073741824 + 536870912
        self.assertEqual(result, expected)

    @patch("app.tm_manager._get_root_apfs_disk")
    def test_returns_zero_when_no_disk_id(self, mock_disk_id):
        """루트 APFS 디스크 식별자를 얻지 못하면 0 반환"""
        mock_disk_id.return_value = None

        result = _try_diskutil_snapshot_size()

        self.assertEqual(result, 0)

    @patch("app.tm_manager.subprocess.run")
    @patch("app.tm_manager._get_root_apfs_disk")
    def test_returns_zero_on_timeout(self, mock_disk_id, mock_run):
        """diskutil 타임아웃 시 0 반환"""
        mock_disk_id.return_value = "disk1s1"
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="diskutil", timeout=30)

        result = _try_diskutil_snapshot_size()

        self.assertEqual(result, 0)

    @patch("app.tm_manager.subprocess.run")
    @patch("app.tm_manager._get_root_apfs_disk")
    def test_returns_zero_on_empty_output(self, mock_disk_id, mock_run):
        """diskutil 출력에 크기 정보가 없으면 0 반환"""
        mock_disk_id.return_value = "disk1s1"
        mock_run.return_value = _make_completed_process(stdout="No snapshots\n")

        result = _try_diskutil_snapshot_size()

        self.assertEqual(result, 0)


# ============================================================
# _get_root_apfs_disk() 내부 헬퍼 테스트
# ============================================================


class TestGetRootApfsDisk(unittest.TestCase):
    """_get_root_apfs_disk() 함수 테스트"""

    @patch("app.tm_manager.subprocess.run")
    def test_extracts_device_identifier(self, mock_run):
        """diskutil info / 출력에서 Device Identifier 추출"""
        mock_run.return_value = _make_completed_process(stdout=DISKUTIL_INFO_OUTPUT)

        result = _get_root_apfs_disk()

        self.assertEqual(result, "disk1s1")

    @patch("app.tm_manager.subprocess.run")
    def test_returns_none_on_missing_identifier(self, mock_run):
        """Device Identifier가 출력에 없으면 None 반환"""
        mock_run.return_value = _make_completed_process(stdout="Some other output\n")

        result = _get_root_apfs_disk()

        self.assertIsNone(result)

    @patch("app.tm_manager.subprocess.run")
    def test_returns_none_on_timeout(self, mock_run):
        """타임아웃 시 None 반환"""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="diskutil", timeout=30)

        result = _get_root_apfs_disk()

        self.assertIsNone(result)

    @patch("app.tm_manager.subprocess.run")
    def test_returns_none_on_file_not_found(self, mock_run):
        """diskutil을 찾지 못할 때 None 반환"""
        mock_run.side_effect = FileNotFoundError()

        result = _get_root_apfs_disk()

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
