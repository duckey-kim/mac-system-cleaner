"""삭제 이력 추적 모듈 -- 삭제 기록 저장 및 통계 제공"""

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from .scanner import format_size

# ============================================================
# 상수
# ============================================================
HISTORY_PATH = os.path.join(str(Path.home()), ".mac_cleaner_history.json")
MAX_RECORDS = 500

_lock = threading.Lock()


# ============================================================
# 내부 헬퍼
# ============================================================
def _load_records():
    """이력 파일에서 레코드 목록 로드"""
    try:
        if os.path.exists(HISTORY_PATH):
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
    except (json.JSONDecodeError, OSError):
        pass
    return []


def _save_records(records):
    """레코드 목록을 이력 파일에 저장"""
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def _time_ago(timestamp_str):
    """ISO 8601 타임스탬프를 한국어 상대 시간 문자열로 변환"""
    try:
        dt = datetime.fromisoformat(timestamp_str)
        # naive datetime이면 로컬 시간으로 간주
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        diff = now - dt
        seconds = int(diff.total_seconds())

        if seconds < 60:
            return "방금 전"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes}분 전"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}시간 전"
        days = hours // 24
        if days < 30:
            return f"{days}일 전"
        months = days // 30
        if months < 12:
            return f"{months}개월 전"
        years = days // 365
        return f"{years}년 전"
    except (ValueError, TypeError):
        return ""


# ============================================================
# 공개 API
# ============================================================
def record_delete(path, size, success):
    """삭제 기록 저장 (thread-safe)

    Args:
        path: 삭제된 경로
        size: 바이트 단위 크기
        success: 삭제 성공 여부
    """
    record = {
        "path": path,
        "name": os.path.basename(path),
        "size": size,
        "success": success,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    with _lock:
        records = _load_records()
        records.append(record)
        # FIFO: 최대 개수 초과 시 오래된 것부터 제거
        if len(records) > MAX_RECORDS:
            records = records[-MAX_RECORDS:]
        _save_records(records)


def get_history(limit=50):
    """최근 삭제 이력 반환 (최신순)

    Args:
        limit: 반환할 최대 레코드 수

    Returns:
        레코드 dict 목록 (size_formatted, time_ago 필드 포함)
    """
    with _lock:
        records = _load_records()

    # 최신순 정렬 후 limit 적용
    records.reverse()
    records = records[:limit]

    for r in records:
        r["size_formatted"] = format_size(r.get("size", 0))
        r["time_ago"] = _time_ago(r.get("timestamp", ""))

    return records


def get_stats():
    """삭제 통계 반환 (성공한 삭제만 집계)

    Returns:
        dict: total_deleted, total_size, this_month, this_month_size 등
    """
    with _lock:
        records = _load_records()

    now = datetime.now(timezone.utc)
    current_year = now.year
    current_month = now.month

    total_deleted = 0
    total_size = 0
    this_month = 0
    this_month_size = 0

    for r in records:
        if not r.get("success"):
            continue
        total_deleted += 1
        total_size += r.get("size", 0)

        # 이번 달 집계
        try:
            dt = datetime.fromisoformat(r["timestamp"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt.year == current_year and dt.month == current_month:
                this_month += 1
                this_month_size += r.get("size", 0)
        except (ValueError, KeyError, TypeError):
            continue

    return {
        "total_deleted": total_deleted,
        "total_size": total_size,
        "total_size_formatted": format_size(total_size),
        "this_month": this_month,
        "this_month_size": this_month_size,
        "this_month_size_formatted": format_size(this_month_size),
    }
