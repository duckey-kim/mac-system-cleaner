"""자동 업데이트 모듈 — 앱 버전 + learned_folders.json 업데이트 + 자동 다운로드"""

import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
import zipfile
from .config import VERSION, GITHUB_REPO, LEARNED_PATH
from .lookup import _load_json, _save_json, _file_lock


# GitHub API / Raw 경로
_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
_DB_RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/app/learned_folders.json"

# 업데이트 결과 (백그라운드 스레드에서 기록, 프론트에서 읽기)
_update_result = {
    "checked": False,
    "app_update": None,
    "db_new_count": 0,
    "error": None,
}

# 다운로드 진행 상태
_download_status = {
    "active": False,
    "progress": 0,       # 0~100
    "status": "",        # "downloading", "extracting", "replacing", "done", "error"
    "message": "",
    "download_url": None,
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
            # 릴리즈 assets에서 .zip 찾기
            download_url = None
            for asset in data.get("assets", []):
                name = asset.get("name", "")
                if name.endswith(".zip"):
                    download_url = asset.get("browser_download_url")
                    break

            result["app_update"] = {
                "version": latest_tag,
                "url": html_url,
                "download_url": download_url,  # .zip asset URL (있으면)
                "body": data.get("body", "")[:200],
                "can_auto_update": _can_auto_update(),
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


def _can_auto_update():
    """자동 업데이트 가능 여부 판별"""
    if getattr(sys, "frozen", False):
        # .app 번들: 실행 파일 경로에서 .app 위치 추출 가능하면 OK
        return _get_app_path() is not None
    else:
        # python3 run.py: git pull 가능한지 확인
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.exists(os.path.join(project_dir, ".git"))


def _get_app_path():
    """현재 .app 번들 경로 찾기 (예: /Applications/System Cleaner.app)"""
    if not getattr(sys, "frozen", False):
        return None
    # sys.executable: .../System Cleaner.app/Contents/MacOS/System Cleaner
    exe = sys.executable
    parts = exe.split(os.sep)
    for i, part in enumerate(parts):
        if part.endswith(".app"):
            return os.sep + os.path.join(*parts[:i + 1])
    return None


def _get_project_dir():
    """프로젝트 루트 디렉토리 (python3 run.py 실행 시)"""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ============================================================
# 실제 업데이트 실행
# ============================================================
def do_update():
    """업데이트 실행. 백그라운드 스레드에서 호출."""
    global _download_status

    if _download_status["active"]:
        return {"success": False, "message": "이미 업데이트 진행 중"}

    _download_status = {
        "active": True, "progress": 0,
        "status": "starting", "message": "업데이트 준비 중...",
        "download_url": None,
    }

    if getattr(sys, "frozen", False):
        # .app 번들 → zip 다운로드 + 교체
        return _update_app_bundle()
    else:
        # python3 run.py → git pull
        return _update_git_pull()


def _update_git_pull():
    """git pull로 업데이트 (python3 run.py 실행 시)"""
    global _download_status
    try:
        project_dir = _get_project_dir()

        _download_status.update(progress=20, status="pulling", message="git pull 실행 중...")

        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=project_dir,
            capture_output=True, text=True, timeout=30,
        )

        if result.returncode == 0:
            _download_status.update(
                progress=100, status="done", active=False,
                message="업데이트 완료! 앱을 재시작하세요.",
            )
            return {"success": True, "message": "git pull 완료. 앱을 재시작하세요.", "restart": True}
        else:
            err = result.stderr[:200] if result.stderr else "알 수 없는 오류"
            _download_status.update(
                progress=0, status="error", active=False,
                message=f"git pull 실패: {err}",
            )
            return {"success": False, "message": f"git pull 실패: {err}"}

    except Exception as e:
        _download_status.update(progress=0, status="error", active=False, message=str(e)[:200])
        return {"success": False, "message": str(e)[:200]}


def _update_app_bundle():
    """GitHub Release에서 .zip 다운로드 → .app 교체"""
    global _download_status
    try:
        update_info = _update_result.get("app_update")
        if not update_info:
            _download_status.update(progress=0, status="error", active=False, message="업데이트 정보 없음")
            return {"success": False, "message": "업데이트 정보 없음"}

        download_url = update_info.get("download_url")
        if not download_url:
            # asset이 없으면 소스 zip 다운로드
            download_url = f"https://github.com/{GITHUB_REPO}/archive/refs/tags/v{update_info['version']}.zip"

        app_path = _get_app_path()
        if not app_path:
            _download_status.update(progress=0, status="error", active=False, message=".app 경로를 찾을 수 없음")
            return {"success": False, "message": ".app 경로를 찾을 수 없음"}

        # 1) 다운로드
        _download_status.update(progress=10, status="downloading", message="다운로드 중...")

        tmp_dir = tempfile.mkdtemp(prefix="mac_cleaner_update_")
        zip_path = os.path.join(tmp_dir, "update.zip")

        req = urllib.request.Request(download_url, headers={"User-Agent": "MacCleaner/" + VERSION})
        with urllib.request.urlopen(req, timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(zip_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = min(60, int(downloaded / total * 50) + 10)
                        _download_status.update(
                            progress=pct,
                            message=f"다운로드 중... {downloaded // 1024 // 1024}MB / {total // 1024 // 1024}MB",
                        )

        _download_status.update(progress=65, status="extracting", message="압축 해제 중...")

        # 2) 압축 해제
        extract_dir = os.path.join(tmp_dir, "extracted")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

        # .app 찾기
        new_app = _find_app_in_dir(extract_dir)
        if not new_app:
            _download_status.update(progress=0, status="error", active=False, message="다운로드에서 .app을 찾을 수 없음")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return {"success": False, "message": ".app을 찾을 수 없음"}

        _download_status.update(progress=80, status="replacing", message="앱 교체 중...")

        # 3) 기존 .app 백업 → 새 .app으로 교체
        backup_path = app_path + ".backup"
        try:
            if os.path.exists(backup_path):
                shutil.rmtree(backup_path)
            shutil.move(app_path, backup_path)
            shutil.move(new_app, app_path)

            # 백업 삭제
            shutil.rmtree(backup_path, ignore_errors=True)
        except PermissionError:
            # 권한 부족 시 osascript로 sudo
            _download_status.update(progress=85, message="관리자 권한으로 교체 중...")
            escaped_app = shlex.quote(app_path)
            escaped_new = shlex.quote(new_app)
            script = f'do shell script "rm -rf {escaped_app} && mv {escaped_new} {escaped_app}" with administrator privileges'
            try:
                subprocess.run(["osascript", "-e", script], timeout=30, check=True)
            except Exception as e:
                # 실패 시 백업 복원
                if os.path.exists(backup_path):
                    shutil.move(backup_path, app_path)
                _download_status.update(progress=0, status="error", active=False, message=f"교체 실패: {str(e)[:100]}")
                shutil.rmtree(tmp_dir, ignore_errors=True)
                return {"success": False, "message": f"교체 실패: {str(e)[:100]}"}

        # 4) 정리
        shutil.rmtree(tmp_dir, ignore_errors=True)

        _download_status.update(progress=100, status="done", active=False, message="업데이트 완료! 앱을 재시작하세요.")
        return {"success": True, "message": "업데이트 완료! 앱을 재시작하세요.", "restart": True}

    except Exception as e:
        _download_status.update(progress=0, status="error", active=False, message=str(e)[:200])
        return {"success": False, "message": str(e)[:200]}


def _find_app_in_dir(directory):
    """디렉토리에서 .app 번들 찾기"""
    for root, dirs, files in os.walk(directory):
        for d in dirs:
            if d.endswith(".app"):
                return os.path.join(root, d)
    return None


def get_download_status():
    """다운로드 진행 상태 반환"""
    return _download_status


# ============================================================
# 기존 함수들
# ============================================================
def _merge_remote_db():
    """GitHub에서 최신 learned_folders.json 가져와서 로컬에 병합."""
    req = urllib.request.Request(
        _DB_RAW_URL,
        headers={"User-Agent": "MacCleaner/" + VERSION},
    )
    with urllib.request.urlopen(req, timeout=8) as resp:
        remote_data = json.loads(resp.read().decode("utf-8"))

    remote_data.pop("_comment", None)

    with _file_lock:
        local_data = _load_json(LEARNED_PATH)
        new_count = 0
        for key, val in remote_data.items():
            if key not in local_data:
                local_data[key] = val
                new_count += 1
        if new_count > 0:
            _save_json(LEARNED_PATH, local_data)

    return new_count


def get_cached_result():
    """마지막 업데이트 확인 결과 반환"""
    return _update_result


def check_update_background(delay=5):
    """백그라운드 스레드에서 업데이트 확인"""
    def _run():
        try:
            check_update()
        except Exception:
            pass

    t = threading.Timer(delay, _run)
    t.daemon = True
    t.start()
