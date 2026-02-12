"""파일 삭제 모듈 — 일반/sudo 삭제 처리"""

import os
import shutil
import subprocess


def delete_path(path, recreate=False, use_sudo=False):
    """경로 삭제 (일반 또는 sudo)"""
    if use_sudo:
        return _delete_sudo(path, recreate)
    else:
        return _delete_normal(path, recreate)


def _delete_normal(path, recreate):
    """일반 삭제"""
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
            if recreate:
                os.makedirs(path, exist_ok=True)
        elif os.path.isfile(path):
            os.remove(path)
        return True, "ok", "삭제 완료"
    except PermissionError:
        return False, "permission_denied", "권한 부족"
    except Exception as e:
        return False, "error", str(e)


def _delete_sudo(path, recreate):
    """sudo 삭제 (osascript로 macOS 네이티브 비밀번호 입력)"""
    try:
        if os.path.isdir(path):
            # 먼저 sudo -n 시도 (비밀번호 캐시가 있으면 바로 삭제)
            result = subprocess.run(
                ["sudo", "-n", "rm", "-rf", path],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                # osascript로 macOS 비밀번호 창 표시
                script = f'do shell script "rm -rf \'{path}\'" with administrator privileges'
                result2 = subprocess.run(
                    ["osascript", "-e", script],
                    capture_output=True, text=True, timeout=120
                )
                if result2.returncode != 0:
                    return False, "sudo_prompt_failed", f"관리자 권한 인증 실패: {result2.stderr.strip()}"
            if recreate:
                os.makedirs(path, exist_ok=True)

        elif os.path.isfile(path):
            script = f'do shell script "rm -f \'{path}\'" with administrator privileges'
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=120
            )
            if result.returncode != 0:
                return False, "sudo_prompt_failed", f"관리자 권한 인증 실패: {result.stderr.strip()}"

        return True, "sudo_ok", "sudo 삭제 완료"

    except subprocess.TimeoutExpired:
        return False, "timeout", "시간 초과 (120초)"
    except Exception as e:
        return False, "error", str(e)
