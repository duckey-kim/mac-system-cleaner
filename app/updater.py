"""자동 업데이트 모듈 — 앱 버전 + learned_folders.json 업데이트"""

import json
import threading
import urllib.request
import urllib.error
from .config import VERSION, GITHUB_REPO, LEARNED_PATH
from .lookup import _load_json, _save_json


# GitHub API / Raw 경로
_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_DB_RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/app/learned_folders.json"

# 업데이트 결과 (백그라운드 스레드에서 기록, 프론트에서 읽기)
_update_result = {
    "checked": False,
    "app_update": None,       # {"version": "3.2", "url": "https://..."}
    "db_new_count": 0,        # 새로 추가된 폴더 수
    "error": None,
}


def check_update():
    """업데이트 확인 (앱 버전 + learned_folders.json). 동기 함수."""
    global _update_result
    result = {
        "checked": True,
        "current_version": VERSION,
        "app_update": None,
        "db_new_count": 0,
        "error": None,
    }

    # 1) 앱 버전 확인
    try:
        req = urllib.request.Request(
            _API_URL,
            headers={"User-Agent": "MacCleaner/" + VERSION},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        latest_tag = data.get("tag_name", "").lstrip("v")
        html_url = data.get("html_url", "")

        if latest_tag and latest_tag != VERSION:
            # 단순 문자열 비교 (semantic versioning은 향후 추가 가능)
            result["app_update"] = {
                "version": latest_tag,
                "url": html_url,
                "body": data.get("body", "")[:200],
            }
    except Exception as e:
        result["error"] = f"앱 버전 확인 실패: {str(e)[:100]}"

    # 2) learned_folders.json 업데이트
    try:
        new_count = _merge_remote_db()
        result["db_new_count"] = new_count
    except Exception as e:
        if result["error"]:
            result["error"] += f" / DB 업데이트 실패: {str(e)[:100]}"
        else:
            result["error"] = f"DB 업데이트 실패: {str(e)[:100]}"

    _update_result = result
    return result


def _merge_remote_db():
    """GitHub에서 최신 learned_folders.json 가져와서 로컬에 병합.
    로컬에만 있는 항목은 유지, 원격에 새로 추가된 것만 합침.
    반환값: 새로 추가된 항목 수"""
    req = urllib.request.Request(
        _DB_RAW_URL,
        headers={"User-Agent": "MacCleaner/" + VERSION},
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        remote_data = json.loads(resp.read().decode("utf-8"))

    remote_data.pop("_comment", None)

    # 로컬 로드
    local_data = _load_json(LEARNED_PATH)

    # 새 항목만 추가 (기존 항목 덮어쓰지 않음)
    new_count = 0
    for key, val in remote_data.items():
        if key not in local_data:
            local_data[key] = val
            new_count += 1

    # 변경 있으면 저장
    if new_count > 0:
        _save_json(LEARNED_PATH, local_data)

    return new_count


def get_cached_result():
    """마지막 업데이트 확인 결과 반환"""
    return _update_result


def check_update_background(delay=5):
    """백그라운드 스레드에서 업데이트 확인 (서버 시작 후 delay초 후)"""
    def _run():
        try:
            check_update()
        except Exception:
            pass

    t = threading.Timer(delay, _run)
    t.daemon = True
    t.start()
