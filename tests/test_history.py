"""history.py 테스트 -- 삭제 이력 기록, 조회, 통계, 상대시간 변환"""

import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch


class _HistoryTestBase(unittest.TestCase):
    """모든 history 테스트의 공통 기반 -- 임시 파일로 HISTORY_PATH 격리"""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        )
        self._tmp.close()
        self._tmp_path = self._tmp.name

        # HISTORY_PATH를 임시 파일로 교체
        self._patcher = patch("app.history.HISTORY_PATH", self._tmp_path)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()
        if os.path.exists(self._tmp_path):
            os.unlink(self._tmp_path)

    def _write_records(self, records):
        """임시 파일에 직접 레코드 기록 (테스트 fixture 용)"""
        with open(self._tmp_path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False)

    def _read_records(self):
        """임시 파일에서 레코드 직접 읽기 (검증 용)"""
        with open(self._tmp_path, "r", encoding="utf-8") as f:
            return json.load(f)


# ============================================================
# record_delete 테스트
# ============================================================
class TestRecordDelete(_HistoryTestBase):
    """record_delete() 함수 테스트"""

    def test_single_entry(self):
        """단일 삭제 기록이 올바르게 저장되는지 확인"""
        from app.history import record_delete

        record_delete("/Users/test/Library/Caches/foo", 1024, True)

        records = self._read_records()
        self.assertEqual(len(records), 1)

        r = records[0]
        self.assertEqual(r["path"], "/Users/test/Library/Caches/foo")
        self.assertEqual(r["name"], "foo")
        self.assertEqual(r["size"], 1024)
        self.assertTrue(r["success"])
        # timestamp가 ISO 8601 형식인지 확인
        dt = datetime.fromisoformat(r["timestamp"])
        self.assertIsNotNone(dt)

    def test_multiple_entries(self):
        """여러 건의 삭제 기록이 순서대로 누적되는지 확인"""
        from app.history import record_delete

        paths = [f"/tmp/cache_{i}" for i in range(5)]
        for p in paths:
            record_delete(p, 512, True)

        records = self._read_records()
        self.assertEqual(len(records), 5)
        # 저장 순서 확인 (append 방식이므로 순서 유지)
        for i, r in enumerate(records):
            self.assertEqual(r["path"], paths[i])

    def test_fifo_max_records(self):
        """MAX_RECORDS 초과 시 오래된 레코드가 제거되는지 확인 (FIFO)"""
        from app.history import record_delete

        small_limit = 10
        with patch("app.history.MAX_RECORDS", small_limit):
            for i in range(small_limit + 5):
                record_delete(f"/tmp/item_{i}", 100, True)

        records = self._read_records()
        self.assertEqual(len(records), small_limit)
        # 가장 오래된 5개(item_0~4)는 제거되고 item_5부터 남아야 함
        self.assertEqual(records[0]["path"], "/tmp/item_5")
        self.assertEqual(records[-1]["path"], f"/tmp/item_{small_limit + 4}")

    def test_thread_safety(self):
        """동시 쓰기가 데이터를 손상시키지 않는지 확인"""
        from app.history import record_delete

        num_threads = 20
        barrier = threading.Barrier(num_threads)

        def worker(idx):
            barrier.wait()  # 모든 스레드가 동시에 시작
            record_delete(f"/tmp/thread_{idx}", 256, True)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        records = self._read_records()
        # 모든 레코드가 손실 없이 저장되었는지 확인
        self.assertEqual(len(records), num_threads)
        # 모든 경로가 유일한지 확인 (중복 없음)
        paths = {r["path"] for r in records}
        self.assertEqual(len(paths), num_threads)

    def test_failed_delete_recorded(self):
        """삭제 실패(success=False) 기록도 정상 저장되는지 확인"""
        from app.history import record_delete

        record_delete("/tmp/fail_target", 0, False)

        records = self._read_records()
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0]["success"])


# ============================================================
# get_history 테스트
# ============================================================
class TestGetHistory(_HistoryTestBase):
    """get_history() 함수 테스트"""

    def _make_record(self, path, size, success, timestamp_str):
        """테스트용 레코드 dict 생성"""
        return {
            "path": path,
            "name": os.path.basename(path),
            "size": size,
            "success": success,
            "timestamp": timestamp_str,
        }

    def test_newest_first(self):
        """반환 결과가 최신순(역순)으로 정렬되는지 확인"""
        from app.history import get_history

        now = datetime.now(timezone.utc)
        records = []
        for i in range(5):
            ts = (now - timedelta(hours=5 - i)).isoformat()
            records.append(self._make_record(f"/tmp/item_{i}", 100, True, ts))
        self._write_records(records)

        result = get_history(limit=50)
        # item_4가 가장 최신이므로 첫 번째
        self.assertEqual(result[0]["path"], "/tmp/item_4")
        self.assertEqual(result[-1]["path"], "/tmp/item_0")

    def test_limit_parameter(self):
        """limit 파라미터가 반환 개수를 제한하는지 확인"""
        from app.history import get_history

        now = datetime.now(timezone.utc)
        records = [
            self._make_record(f"/tmp/item_{i}", 100, True, now.isoformat())
            for i in range(20)
        ]
        self._write_records(records)

        result = get_history(limit=5)
        self.assertEqual(len(result), 5)

    def test_empty_history(self):
        """이력이 없을 때 빈 리스트를 반환하는지 확인"""
        from app.history import get_history

        # 빈 파일 상태
        self._write_records([])
        result = get_history()
        self.assertEqual(result, [])

    def test_empty_file(self):
        """이력 파일이 비어 있을 때(JSON 없음) 빈 리스트를 반환하는지 확인"""
        from app.history import get_history

        # 파일 내용을 완전히 비움
        with open(self._tmp_path, "w") as f:
            f.write("")
        result = get_history()
        self.assertEqual(result, [])

    def test_includes_formatted_fields(self):
        """size_formatted와 time_ago 필드가 추가되는지 확인"""
        from app.history import get_history

        now = datetime.now(timezone.utc)
        records = [
            self._make_record("/tmp/test", 1048576, True, now.isoformat())
        ]
        self._write_records(records)

        result = get_history()
        r = result[0]
        self.assertIn("size_formatted", r)
        self.assertIn("time_ago", r)
        # 1 MB = 1048576 bytes
        self.assertEqual(r["size_formatted"], "1.0 MB")

    def test_record_has_expected_keys(self):
        """각 레코드가 필수 키를 모두 포함하는지 확인"""
        from app.history import get_history

        now = datetime.now(timezone.utc)
        records = [
            self._make_record("/tmp/test", 512, True, now.isoformat())
        ]
        self._write_records(records)

        result = get_history()
        r = result[0]
        expected_keys = {
            "path", "name", "size", "success",
            "timestamp", "size_formatted", "time_ago",
        }
        self.assertEqual(set(r.keys()), expected_keys)


# ============================================================
# get_stats 테스트
# ============================================================
class TestGetStats(_HistoryTestBase):
    """get_stats() 함수 테스트"""

    def _make_record(self, size, success, timestamp_str):
        """통계 테스트용 간략 레코드 생성"""
        return {
            "path": "/tmp/stats_test",
            "name": "stats_test",
            "size": size,
            "success": success,
            "timestamp": timestamp_str,
        }

    def test_counts_only_successful(self):
        """성공한 삭제만 total_deleted에 집계되는지 확인"""
        from app.history import get_stats

        now = datetime.now(timezone.utc).isoformat()
        records = [
            self._make_record(100, True, now),
            self._make_record(200, False, now),  # 실패 -- 제외
            self._make_record(300, True, now),
        ]
        self._write_records(records)

        stats = get_stats()
        self.assertEqual(stats["total_deleted"], 2)

    def test_total_size_calculation(self):
        """total_size가 성공 레코드의 size 합산인지 확인"""
        from app.history import get_stats

        now = datetime.now(timezone.utc).isoformat()
        records = [
            self._make_record(1000, True, now),
            self._make_record(2000, True, now),
            self._make_record(5000, False, now),  # 실패 -- 제외
        ]
        self._write_records(records)

        stats = get_stats()
        self.assertEqual(stats["total_size"], 3000)

    def test_this_month_counts_current_month_only(self):
        """this_month가 현재 달 레코드만 집계하는지 확인"""
        from app.history import get_stats

        now = datetime.now(timezone.utc)
        last_month = now.replace(day=1) - timedelta(days=1)

        records = [
            self._make_record(100, True, now.isoformat()),
            self._make_record(200, True, now.isoformat()),
            self._make_record(300, True, last_month.isoformat()),  # 지난달 -- this_month 제외
        ]
        self._write_records(records)

        stats = get_stats()
        self.assertEqual(stats["this_month"], 2)
        self.assertEqual(stats["this_month_size"], 300)
        # total은 3건 모두 포함
        self.assertEqual(stats["total_deleted"], 3)

    def test_empty_history_returns_zeros(self):
        """이력이 없을 때 모든 통계가 0인지 확인"""
        from app.history import get_stats

        self._write_records([])

        stats = get_stats()
        self.assertEqual(stats["total_deleted"], 0)
        self.assertEqual(stats["total_size"], 0)
        self.assertEqual(stats["this_month"], 0)
        self.assertEqual(stats["this_month_size"], 0)

    def test_includes_formatted_fields(self):
        """_formatted 접미 필드가 포함되는지 확인"""
        from app.history import get_stats

        now = datetime.now(timezone.utc).isoformat()
        records = [self._make_record(1048576, True, now)]
        self._write_records(records)

        stats = get_stats()
        self.assertIn("total_size_formatted", stats)
        self.assertIn("this_month_size_formatted", stats)
        self.assertEqual(stats["total_size_formatted"], "1.0 MB")


# ============================================================
# _time_ago 테스트
# ============================================================
class TestTimeAgo(_HistoryTestBase):
    """_time_ago() 내부 함수 테스트"""

    def test_just_now(self):
        """60초 미만이면 '방금 전' 반환"""
        from app.history import _time_ago

        now = datetime.now(timezone.utc)
        ts = (now - timedelta(seconds=30)).isoformat()
        self.assertEqual(_time_ago(ts), "방금 전")

    def test_minutes(self):
        """1~59분 범위에서 'N분 전' 형식 반환"""
        from app.history import _time_ago

        now = datetime.now(timezone.utc)
        ts = (now - timedelta(minutes=15)).isoformat()
        result = _time_ago(ts)
        self.assertIn("분 전", result)
        self.assertTrue(result.startswith("15") or result.startswith("14"))

    def test_hours(self):
        """1~23시간 범위에서 'N시간 전' 형식 반환"""
        from app.history import _time_ago

        now = datetime.now(timezone.utc)
        ts = (now - timedelta(hours=3)).isoformat()
        result = _time_ago(ts)
        self.assertIn("시간 전", result)
        self.assertTrue(result.startswith("3"))

    def test_days(self):
        """1~29일 범위에서 'N일 전' 형식 반환"""
        from app.history import _time_ago

        now = datetime.now(timezone.utc)
        ts = (now - timedelta(days=7)).isoformat()
        result = _time_ago(ts)
        self.assertIn("일 전", result)
        self.assertTrue(result.startswith("7"))

    def test_months(self):
        """30일 이상~365일 미만에서 'N개월 전' 형식 반환"""
        from app.history import _time_ago

        now = datetime.now(timezone.utc)
        ts = (now - timedelta(days=90)).isoformat()
        result = _time_ago(ts)
        self.assertIn("개월 전", result)

    def test_years(self):
        """365일 이상에서 'N년 전' 형식 반환"""
        from app.history import _time_ago

        now = datetime.now(timezone.utc)
        ts = (now - timedelta(days=400)).isoformat()
        result = _time_ago(ts)
        self.assertIn("년 전", result)

    def test_invalid_timestamp_returns_empty(self):
        """잘못된 타임스탬프에 대해 빈 문자열 반환"""
        from app.history import _time_ago

        self.assertEqual(_time_ago("not-a-timestamp"), "")
        self.assertEqual(_time_ago(""), "")
        self.assertEqual(_time_ago(None), "")

    def test_naive_datetime_handled(self):
        """timezone 정보 없는 naive datetime 문자열도 처리"""
        from app.history import _time_ago

        now = datetime.now(timezone.utc)
        # timezone 없는 ISO 형식
        ts = (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S")
        result = _time_ago(ts)
        # 빈 문자열이 아닌 유효한 상대 시간이 반환되어야 함
        self.assertNotEqual(result, "")
        self.assertIn("분 전", result)


if __name__ == "__main__":
    unittest.main()
