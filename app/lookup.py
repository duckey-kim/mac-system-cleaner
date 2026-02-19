"""폴더 설명 자동 조회 모듈 — 패턴 매칭 + 웹 검색 + 영구 저장"""

import json
import os
import re
import tempfile
import threading
import urllib.request
import urllib.parse
from pathlib import Path

from .config import LEARNED_PATH, VERSION

# ============================================================
# 저장소 경로
# ============================================================
# 임시 캐시: 홈 디렉토리 (빠른 조회용, 없어져도 OK)
CACHE_PATH = os.path.join(str(Path.home()), ".mac_cleaner_cache.json")


# ============================================================
# 1단계: 패턴 매칭 (오프라인, 즉시)
# ============================================================
BUNDLE_PREFIXES = {
    "com.apple": ("Apple 시스템/앱 데이터", "moderate"),
    "com.google": ("Google 앱 데이터", "moderate"),
    "com.microsoft": ("Microsoft 앱 데이터", "moderate"),
    "com.jetbrains": ("JetBrains IDE 데이터", "safe"),
    "com.adobe": ("Adobe 앱 데이터", "moderate"),
    "com.spotify": ("Spotify 데이터", "moderate"),
    "com.slack": ("Slack 데이터", "moderate"),
    "com.discord": ("Discord 데이터", "moderate"),
    "com.brave": ("Brave 브라우저 데이터", "moderate"),
    "com.electron": ("Electron 앱 데이터", "moderate"),
    "com.github": ("GitHub 앱 데이터", "moderate"),
    "org.mozilla": ("Mozilla/Firefox 데이터", "moderate"),
    "io.flutter": ("Flutter 관련 데이터", "safe"),
    "org.chromium": ("Chromium 기반 브라우저 데이터", "moderate"),
    "com.tencent": ("Tencent 앱 데이터", "moderate"),
    "com.kakao": ("카카오 앱 데이터", "moderate"),
    "net.line": ("LINE 앱 데이터", "moderate"),
}

KEYWORD_PATTERNS = [
    (r"(?i)cache", "캐시 폴더. 삭제해도 앱 실행 시 재생성됨.", "safe"),
    (r"(?i)log(s)?$", "로그 파일. 삭제해도 안전.", "safe"),
    (r"(?i)temp|tmp", "임시 파일. 삭제해도 안전.", "safe"),
    (r"(?i)crash", "크래시 리포트. 디버깅 불필요 시 삭제 가능.", "safe"),
    (r"(?i)backup", "백업 데이터. 삭제 전 확인 필요.", "caution"),
    (r"(?i)saved?\s?state", "앱 상태 저장 데이터.", "moderate"),
    (r"(?i)cookie", "쿠키 데이터.", "moderate"),
    (r"(?i)update", "업데이트 관련 파일.", "moderate"),
    (r"(?i)download", "다운로드 파일.", "moderate"),
    (r"(?i)data(base)?s?$", "데이터 저장소. 삭제 시 데이터 손실 가능.", "caution"),
    (r"(?i)socket", "소켓 파일. 임시 통신용.", "safe"),
    (r"(?i)preferences|pref", "앱 설정 파일. 삭제 시 설정 초기화.", "caution"),
    (r"node_modules", "Node.js 패키지. npm/yarn install로 재생성.", "safe"),
    (r"\.git$", "Git 저장소 데이터. 삭제 시 이력 손실!", "caution"),
    (r"(?i)build|dist|out(put)?$", "빌드 산출물. 재빌드로 재생성.", "safe"),
    (r"__pycache__", "Python 바이트코드 캐시. 삭제해도 안전.", "safe"),
    (r"\.pyc$", "Python 컴파일 캐시.", "safe"),
    (r"(?i)vendor", "패키지 의존성. 패키지 매니저로 재설치 가능.", "safe"),
    (r"(?i)pods?$", "CocoaPods 의존성. pod install로 재생성.", "safe"),
    (r"(?i)framework", "프레임워크 파일. 앱 실행에 필요할 수 있음.", "caution"),
    (r"(?i)plugin|extension|addon", "플러그인/확장. 삭제 시 기능 손실.", "moderate"),
    (r"(?i)migration", "데이터베이스 마이그레이션. 삭제 시 문제 가능.", "caution"),
    (r"(?i)session", "세션 데이터. 삭제 시 로그아웃됨.", "moderate"),
    (r"(?i)thumbnail|thumb", "썸네일 캐시. 삭제해도 자동 재생성.", "safe"),
    (r"(?i)index|metadata", "인덱스/메타데이터. 삭제 시 재색인 필요.", "moderate"),
]


def pattern_match(name, path=""):
    """폴더 이름/경로 패턴으로 설명 추측"""
    # 1) 번들 ID 매칭 (com.apple.xxx 등)
    for prefix, (desc, risk) in BUNDLE_PREFIXES.items():
        if name.startswith(prefix) or name.lower().startswith(prefix):
            # 번들 ID에서 앱 이름 추출
            parts = name.split(".")
            app_name = parts[-1] if len(parts) > 2 else name
            return f"{desc} ({app_name})", risk

    # 2) 키워드 패턴 매칭
    for pattern, desc, risk in KEYWORD_PATTERNS:
        if re.search(pattern, name):
            return desc, risk

    # 3) 경로 기반 추측
    if path:
        if "/Caches/" in path:
            return f"{name} 캐시 데이터. 삭제해도 재생성 가능.", "safe"
        elif "/Logs/" in path:
            return f"{name} 로그. 삭제해도 안전.", "safe"
        elif "/Application Support/" in path:
            return f"{name} 앱 데이터. 삭제 시 설정/데이터 손실 가능.", "moderate"
        elif "/Containers/" in path:
            return f"{name} 앱 샌드박스 데이터.", "moderate"
        elif "/Developer/" in path:
            return f"{name} 개발 도구 데이터.", "moderate"

    return None, None


# ============================================================
# 2단계: 웹 검색 (DuckDuckGo API, 무료/키 불필요)
# ============================================================
def web_search(name, path=""):
    """DuckDuckGo API로 폴더 설명 검색"""
    try:
        # 검색어 구성
        query = f"macOS {name} folder what is"
        if path and "/Library/" in path:
            query = f"macOS Library {name} folder"

        url = (
            "https://api.duckduckgo.com/?q="
            + urllib.parse.quote(query)
            + "&format=json&no_html=1&skip_disambig=1"
        )

        req = urllib.request.Request(url, headers={"User-Agent": "MacCleaner/" + VERSION})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        # Abstract (가장 좋은 결과)
        abstract = data.get("AbstractText", "").strip()
        if abstract and len(abstract) > 20:
            return _summarize(abstract, name), "moderate"

        # Related Topics
        for topic in data.get("RelatedTopics", []):
            if isinstance(topic, dict) and "Text" in topic:
                text = topic["Text"].strip()
                if len(text) > 20:
                    return _summarize(text, name), "moderate"

        # Infobox
        infobox = data.get("Infobox", {})
        if infobox and "content" in infobox:
            for item in infobox["content"]:
                if "value" in item:
                    return str(item["value"])[:150], "moderate"

    except Exception:
        pass

    return None, None


def _summarize(text, name):
    """긴 텍스트를 150자 이내로 요약"""
    text = text.strip()
    if len(text) <= 150:
        return text

    # 첫 문장만 추출
    for sep in [". ", ".\n", ".\t"]:
        idx = text.find(sep)
        if 0 < idx < 200:
            return text[: idx + 1]

    return text[:147] + "..."


# ============================================================
# 저장소 관리 (영구 + 캐시 2단계)
# ============================================================
def _load_json(path):
    """JSON 파일 로드 (실패 시 빈 dict)"""
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # _comment 키 제거 (메타데이터)
                data.pop("_comment", None)
                return data
    except Exception:
        pass
    return {}


_file_lock = threading.Lock()


def _save_json(path, data):
    """JSON 파일 저장 (키별 한 줄 compact 형식, atomic write)"""
    tmp_path = None
    try:
        lines = []
        for key, val in data.items():
            lines.append(f'"{key}":{json.dumps(val, ensure_ascii=False, separators=(",", ":"))}')
        content = "{\n" + ",\n".join(lines) + "\n}\n"
        dir_name = os.path.dirname(path)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=dir_name, suffix=".tmp",
            delete=False, encoding="utf-8"
        ) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        os.replace(tmp_path, path)
    except Exception:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def _load_learned():
    """영구 저장소 로드"""
    return _load_json(LEARNED_PATH)


def _save_learned(learned):
    """영구 저장소 저장"""
    _save_json(LEARNED_PATH, learned)


def _load_cache():
    """임시 캐시 로드"""
    return _load_json(CACHE_PATH)


def _save_cache(cache):
    """임시 캐시 저장"""
    _save_json(CACHE_PATH, cache)


# ============================================================
# 통합 조회 함수
# ============================================================
def lookup_folder(name, path=""):
    """폴더 설명 조회 (영구저장소 → 캐시 → 패턴 → 웹 검색 순)"""

    cache_key = name.lower()

    with _file_lock:
        # 0단계: 영구 저장소 확인 (프로젝트 안, 캐시 지워도 살아있음)
        learned = _load_learned()
        if cache_key in learned:
            entry = learned[cache_key]
            return {
                "desc": entry["desc"],
                "risk": entry["risk"],
                "source": entry.get("source", "learned"),
            }

        # 0.5단계: 임시 캐시 확인 (빠른 조회)
        cache = _load_cache()
        if cache_key in cache:
            entry = cache[cache_key]
            return {
                "desc": entry["desc"],
                "risk": entry["risk"],
                "source": entry.get("source", "cache"),
            }

        # 1단계: 패턴 매칭
        desc, risk = pattern_match(name, path)
        if desc:
            result = {"desc": desc, "risk": risk, "source": "pattern"}
            learned[cache_key] = result
            _save_learned(learned)
            cache[cache_key] = result
            _save_cache(cache)
            return result

    # 2단계: 웹 검색 (lock 밖에서 — 네트워크 I/O는 오래 걸림)
    desc, risk = web_search(name, path)
    if desc:
        result = {"desc": desc, "risk": risk, "source": "web"}
        with _file_lock:
            learned = _load_learned()
            learned[cache_key] = result
            _save_learned(learned)
            cache = _load_cache()
            cache[cache_key] = result
            _save_cache(cache)
        return result

    # 못 찾음 — 캐시에만 저장
    with _file_lock:
        cache = _load_cache()
        cache[cache_key] = {"desc": "정보 없음", "risk": "unknown", "source": "none"}
        _save_cache(cache)
    return {"desc": "정보 없음", "risk": "unknown", "source": "none"}
