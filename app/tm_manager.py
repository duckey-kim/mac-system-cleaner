"""Time Machine 로컬 스냅샷 관리 모듈"""

import re
import shlex
import subprocess

from .scanner import format_size

# ============================================================
# 상수
# ============================================================
TMUTIL_TIMEOUT = 30          # tmutil 명령 타임아웃 (초)
OSASCRIPT_TIMEOUT = 120      # osascript 비밀번호 창 타임아웃 (초)

# com.apple.TimeMachine.2025-01-15-123456.local 에서 날짜 부분 추출
_SNAPSHOT_RE = re.compile(
    r"com\.apple\.TimeMachine\.(\d{4}-\d{2}-\d{2}-\d{6})\.local"
)


def list_snapshots():
    """로컬 Time Machine 스냅샷 목록 반환

    Returns:
        list[dict]: [{"date": "2025-01-15-123456",
                       "display": "2025-01-15 12:34:56"}, ...]
        빈 리스트: 스냅샷 없거나 tmutil 실행 실패
    """
    try:
        result = subprocess.run(
            ["tmutil", "listlocalsnapshots", "/"],
            capture_output=True, text=True, timeout=TMUTIL_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []

    snapshots = []
    for line in result.stdout.splitlines():
        m = _SNAPSHOT_RE.search(line)
        if not m:
            continue
        date_raw = m.group(1)  # "2025-01-15-123456"
        # 표시용 포맷: "2025-01-15 12:34:56"
        display = _format_display(date_raw)
        snapshots.append({"date": date_raw, "display": display})

    return snapshots


def delete_snapshot(date_str):
    """단일 스냅샷 삭제

    Args:
        date_str: "2025-01-15-123456" 형식의 날짜 문자열

    Returns:
        tuple[bool, str]: (성공 여부, 결과 메시지)
    """
    safe_date = shlex.quote(date_str)

    # 1차 시도: sudo -n (캐시된 sudo 세션 활용)
    try:
        result = subprocess.run(
            ["sudo", "-n", "tmutil", "deletelocalsnapshots", date_str],
            capture_output=True, text=True, timeout=TMUTIL_TIMEOUT,
        )
        if result.returncode == 0:
            return True, f"스냅샷 삭제 완료: {date_str}"
    except subprocess.TimeoutExpired:
        return False, f"시간 초과: {date_str}"
    except (FileNotFoundError, OSError) as e:
        return False, f"실행 오류: {e}"

    # 2차 시도: osascript로 macOS 관리자 비밀번호 창 표시
    try:
        script = (
            f'do shell script "tmutil deletelocalsnapshots {safe_date}"'
            f" with administrator privileges"
        )
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=OSASCRIPT_TIMEOUT,
        )
        if result.returncode == 0:
            return True, f"스냅샷 삭제 완료: {date_str}"
        return False, f"관리자 권한 인증 실패: {result.stderr.strip()}"
    except subprocess.TimeoutExpired:
        return False, f"시간 초과 (관리자 인증): {date_str}"
    except (FileNotFoundError, OSError) as e:
        return False, f"실행 오류: {e}"


def delete_all_snapshots():
    """모든 로컬 스냅샷 순차 삭제

    Returns:
        tuple[int, int, str]: (성공 수, 실패 수, 요약 메시지)
    """
    snapshots = list_snapshots()
    if not snapshots:
        return 0, 0, "삭제할 스냅샷이 없습니다"

    success_count = 0
    fail_count = 0

    for snap in snapshots:
        ok, _ = delete_snapshot(snap["date"])
        if ok:
            success_count += 1
        else:
            fail_count += 1

    total = success_count + fail_count
    msg = f"전체 {total}개 중 {success_count}개 삭제 완료"
    if fail_count:
        msg += f", {fail_count}개 실패"

    return success_count, fail_count, msg


def get_snapshots_size():
    """로컬 스냅샷 총 크기 추정

    tmutil listlocalsnapshots / 의 출력에서 크기 정보를 파싱한다.
    macOS 버전에 따라 크기 정보가 포함되지 않을 수 있으므로,
    실패 시 diskutil을 통해 purgeable space로 추정한다.

    Returns:
        tuple[int, str]: (바이트 크기, 포맷된 문자열)
        크기 판별 불가 시 (0, "N/A")
    """
    # 방법 1: tmutil listlocalsnapshots / 출력에서 크기 파싱
    #   일부 macOS 버전은 "(<size>)" 형식으로 크기를 포함
    size = _try_tmutil_size()
    if size > 0:
        return size, format_size(size)

    # 방법 2: diskutil apfs listSnapshots / 에서 크기 합산
    size = _try_diskutil_snapshot_size()
    if size > 0:
        return size, format_size(size)

    return 0, "N/A"


# ============================================================
# 내부 헬퍼
# ============================================================

def _format_display(date_raw):
    """날짜 문자열을 표시용으로 변환

    "2025-01-15-123456" -> "2025-01-15 12:34:56"
    """
    # date_raw: YYYY-MM-DD-HHMMSS
    if len(date_raw) != 17:
        return date_raw
    date_part = date_raw[:10]            # "2025-01-15"
    time_part = date_raw[11:]            # "123456"
    if len(time_part) != 6:
        return date_raw
    formatted_time = f"{time_part[0:2]}:{time_part[2:4]}:{time_part[4:6]}"
    return f"{date_part} {formatted_time}"


def _try_tmutil_size():
    """tmutil 출력에서 스냅샷 크기 추출 시도

    일부 macOS에서 각 스냅샷 라인에 바이트 크기가 표시됨.
    예: "com.apple.TimeMachine.2025-01-15-123456.local (1.2GB)"
    """
    try:
        result = subprocess.run(
            ["tmutil", "listlocalsnapshots", "/"],
            capture_output=True, text=True, timeout=TMUTIL_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return 0

    total = 0
    # 괄호 안의 크기 정보 파싱: (123456789) 또는 (1.2GB) 등
    size_pattern = re.compile(r"\((\d+(?:\.\d+)?)\s*(B|KB|MB|GB|TB)\)", re.IGNORECASE)
    multipliers = {"b": 1, "kb": 1024, "mb": 1024**2, "gb": 1024**3, "tb": 1024**4}

    for line in result.stdout.splitlines():
        m = size_pattern.search(line)
        if m:
            value = float(m.group(1))
            unit = m.group(2).lower()
            total += int(value * multipliers.get(unit, 1))

    return total


def _try_diskutil_snapshot_size():
    """diskutil apfs listSnapshots 에서 스냅샷 크기 합산 시도"""
    # 먼저 루트 볼륨의 APFS 디스크 식별자 가져오기
    disk_id = _get_root_apfs_disk()
    if not disk_id:
        return 0

    try:
        result = subprocess.run(
            ["diskutil", "apfs", "listSnapshots", disk_id],
            capture_output=True, text=True, timeout=TMUTIL_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return 0

    total = 0
    # "Snapshot Disk Size" 또는 "Snapshot Size" 라인에서 바이트 추출
    # 예: "Snapshot Disk Size:  1234567890 B (1.1 GB)"
    byte_pattern = re.compile(r"Snapshot.*Size.*?:\s*(\d+)\s*B", re.IGNORECASE)
    for line in result.stdout.splitlines():
        m = byte_pattern.search(line)
        if m:
            total += int(m.group(1))

    return total


def _get_root_apfs_disk():
    """루트 파일시스템의 APFS 디스크 식별자 반환 (예: "disk1s1")"""
    try:
        result = subprocess.run(
            ["diskutil", "info", "/"],
            capture_output=True, text=True, timeout=TMUTIL_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None

    for line in result.stdout.splitlines():
        if "Device Identifier" in line:
            parts = line.split(":", 1)
            if len(parts) == 2:
                return parts[1].strip()

    return None
