"""설정 및 알려진 폴더 데이터베이스"""

import json
import os
import sys
from pathlib import Path

PORT = 8787
HOME = str(Path.home())


# ============================================================
# 폴더 DB: learned_folders.json 에서 로드 (한 파일로 통합 관리)
# ============================================================
def _get_learned_path():
    """learned_folders.json 경로 (PyInstaller 번들 호환)"""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "learned_folders.json")


LEARNED_PATH = _get_learned_path()


def _load_all_folders():
    """learned_folders.json 로드 → dict 반환"""
    try:
        if os.path.exists(LEARNED_PATH):
            with open(LEARNED_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                data.pop("_comment", None)
                return data
    except Exception:
        pass
    return {}


# 앱 시작 시 한 번 로드
KNOWN_FOLDERS = _load_all_folders()


def get_folder_info(name):
    """폴더 이름으로 설명/위험도 반환 (소문자 키 매칭)"""
    info = KNOWN_FOLDERS.get(name.lower())
    if info:
        return info["desc"], info["risk"]
    return "", "unknown"
