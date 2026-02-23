"""파일 시스템 스캔 모듈 — 카테고리별 병렬 스캔으로 시스템 전체 탐색"""

import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import HOME, get_folder_info

# ============================================================
# 스캔 임계값 상수
# ============================================================
MIN_GROUP_MB = 50              # ~/Library depth-1 그룹 최소 크기
MIN_ITEM_MB = 20               # ~/Library depth-2 항목 최소 크기
MIN_CHILD_BYTES = 512 * 1024   # drill-down 항목 최소 크기 (512KB)
MAX_ITEMS_PER_GROUP = 20       # 그룹당 최대 항목 수
MAX_CHILDREN = 30              # drill-down 최대 항목 수
DU_TIMEOUT = 120               # du 명령 타임아웃 (초)

# 카테고리별 최소 크기 (MB)
MIN_DEV_CACHE_MB = 10
MIN_DOWNLOAD_MB = 20
MIN_TRASH_MB = 1
MIN_MEDIA_MB = 50
MIN_LOG_MB = 5

# ============================================================
# 카테고리 정의
# ============================================================
CATEGORY_META = {
    "app_data":     "앱 데이터 (~/Library)",
    "dev_cache":    "개발자 캐시",
    "downloads":    "다운로드 폴더",
    "trash":        "휴지통",
    "media":        "대용량 미디어",
    "system_logs":  "시스템 로그",
}

CATEGORY_ORDER = ["app_data", "dev_cache", "downloads", "trash", "media", "system_logs"]

# 개발자 캐시 경로 목록 (HOME 상대 경로)
DEV_CACHE_PATHS = [
    (".npm", "npm 패키지 캐시"),
    (".yarn", "Yarn 패키지 캐시"),
    (".pnpm-store", "pnpm 패키지 저장소"),
    (".gradle", "Gradle 빌드 캐시"),
    (".m2", "Maven 로컬 저장소"),
    (".docker", "Docker 데이터"),
    (".pub-cache", "Dart/Flutter pub 캐시"),
    (".cocoapods", "CocoaPods 캐시"),
    (".cargo", "Rust Cargo 캐시"),
    (".rustup", "Rust toolchain"),
    (".gem", "Ruby Gem 캐시"),
    (".composer", "PHP Composer 캐시"),
    (".nuget", "NuGet 패키지 캐시"),
    (".conda", "Conda 환경"),
    (".nvm", "nvm Node.js 버전"),
    (".pyenv", "pyenv Python 버전"),
    (".rbenv", "rbenv Ruby 버전"),
]


def format_size(size_bytes):
    """바이트를 사람 읽기 형태로"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 ** 2:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 ** 3:
        return f"{size_bytes / (1024**2):.1f} MB"
    else:
        return f"{size_bytes / (1024**3):.2f} GB"


def _parse_du(output, base_path):
    """du 출력을 파싱하여 {path: size_bytes} dict 반환"""
    sizes = {}
    for line in output.strip().split("\n"):
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        try:
            path = parts[1]
            if path != base_path:
                sizes[path] = int(parts[0]) * 1024
        except ValueError:
            continue
    return sizes


def get_children_sizes(parent_path):
    """du -d1 -k 로 하위 폴더 크기를 한 번에 가져오기 (drill-down용)"""
    try:
        result = subprocess.run(
            ["du", "-d1", "-k", parent_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode in (0, 1):  # 1 = 일부 경로 권한 오류 (무시 가능)
            return _parse_du(result.stdout, parent_path)
    except Exception:
        pass
    return {}


def get_disk_info():
    """shutil.disk_usage로 정확한 디스크 정보 반환"""
    try:
        usage = shutil.disk_usage("/")
        total = usage.total
        used = usage.used
        free = usage.free
        percent = round((used / total) * 100)
        return {
            "total": format_size(total),
            "used": format_size(used),
            "available": format_size(free),
            "percent": f"{percent}%",
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
        }
    except Exception:
        return {
            "total": "N/A", "used": "N/A", "available": "N/A",
            "percent": "N/A", "total_bytes": 0, "used_bytes": 0, "free_bytes": 0,
        }


def _make_item(path, name, size):
    """스캔 결과 항목 하나를 dict로 구성"""
    try:
        if os.path.islink(path):
            return None
        is_dir = os.path.isdir(path)
        children_count = 0
        if is_dir:
            try:
                children_count = len(os.listdir(path))
            except Exception:
                pass
        desc, risk = get_folder_info(name)
        return {
            "name": name,
            "path": path,
            "size": size,
            "size_formatted": format_size(size),
            "is_dir": is_dir,
            "children_count": children_count,
            "description": desc,
            "risk": risk,
            "drillable": is_dir and children_count > 0,
        }
    except Exception:
        return None


# ============================================================
# 카테고리별 스캔 함수
# ============================================================

def _scan_library():
    """~/Library 스캔 (du -d2) -> groups 목록 반환"""
    library_path = os.path.join(HOME, "Library")
    min_group_bytes = MIN_GROUP_MB * 1024 * 1024
    min_item_bytes = MIN_ITEM_MB * 1024 * 1024

    all_sizes = {}
    try:
        result = subprocess.run(
            ["du", "-d2", "-k", library_path],
            capture_output=True, text=True, timeout=DU_TIMEOUT
        )
        if result.returncode in (0, 1):
            all_sizes = _parse_du(result.stdout, library_path)
    except Exception:
        pass

    d1_sizes = {}
    d2_by_parent = {}

    for path, size in all_sizes.items():
        rel = os.path.relpath(path, library_path)
        segments = rel.split(os.sep)
        if len(segments) == 1:
            d1_sizes[path] = size
        elif len(segments) == 2:
            parent = os.path.join(library_path, segments[0])
            d2_by_parent.setdefault(parent, []).append(
                (path, size, segments[1])
            )

    groups = []
    for d1_path in sorted(d1_sizes, key=d1_sizes.get, reverse=True):
        d1_size = d1_sizes[d1_path]
        if d1_size < min_group_bytes:
            continue

        folder_name = os.path.basename(d1_path)

        items = []
        for d2_path, d2_size, d2_name in d2_by_parent.get(d1_path, []):
            if d2_size < min_item_bytes:
                continue
            item = _make_item(d2_path, d2_name, d2_size)
            if item:
                items.append(item)

        items.sort(key=lambda x: x["size"], reverse=True)

        if not items:
            item = _make_item(d1_path, folder_name, d1_size)
            if item:
                items.append(item)

        if items:
            total_size = sum(it["size"] for it in items)
            groups.append({
                "label": f"Library/{folder_name}",
                "path": d1_path,
                "items": items[:MAX_ITEMS_PER_GROUP],
                "total_size": total_size,
                "total_size_formatted": format_size(total_size),
            })

    return groups


def _get_dir_total(du_stdout, dir_path):
    """du 출력에서 디렉토리 자체의 전체 크기를 추출"""
    for line in du_stdout.strip().split("\n"):
        parts = line.split("\t", 1)
        if len(parts) == 2 and parts[1] == dir_path:
            try:
                return int(parts[0]) * 1024
            except ValueError:
                pass
    return 0


def _scan_simple_dir(dir_path, label, min_mb):
    """단일 디렉토리를 du -d1로 스캔 -> groups 목록 반환 (공용)"""
    if not os.path.isdir(dir_path):
        return []
    min_bytes = min_mb * 1024 * 1024

    try:
        result = subprocess.run(
            ["du", "-d1", "-k", dir_path],
            capture_output=True, text=True, timeout=DU_TIMEOUT
        )
        if result.returncode not in (0, 1):
            return []
    except Exception:
        return []

    child_sizes = _parse_du(result.stdout, dir_path)
    total_bytes = _get_dir_total(result.stdout, dir_path)

    if total_bytes < min_bytes:
        return []

    min_item_bytes = max(MIN_CHILD_BYTES, min_mb * 512 * 1024)
    items = []
    for child_path, child_size in child_sizes.items():
        if child_size < min_item_bytes:
            continue
        name = os.path.basename(child_path)
        item = _make_item(child_path, name, child_size)
        if item:
            items.append(item)
    items.sort(key=lambda x: x["size"], reverse=True)

    if not items:
        item = _make_item(dir_path, label, total_bytes)
        if item:
            items.append(item)

    if items:
        return [{
            "label": label,
            "path": dir_path,
            "items": items[:MAX_ITEMS_PER_GROUP],
            "total_size": total_bytes,
            "total_size_formatted": format_size(total_bytes),
        }]
    return []


def _scan_dev_caches():
    """개발자 캐시 경로 스캔 -> groups 목록 반환"""
    min_bytes = MIN_DEV_CACHE_MB * 1024 * 1024
    groups = []
    for rel_path, _desc in DEV_CACHE_PATHS:
        full_path = os.path.join(HOME, rel_path)
        if not os.path.isdir(full_path):
            continue
        try:
            result = subprocess.run(
                ["du", "-d1", "-k", full_path],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode not in (0, 1):
                continue
        except Exception:
            continue

        child_sizes = _parse_du(result.stdout, full_path)
        total_bytes = _get_dir_total(result.stdout, full_path)

        if total_bytes < min_bytes:
            continue

        items = []
        for child_path, child_size in child_sizes.items():
            if child_size < MIN_CHILD_BYTES:
                continue
            name = os.path.basename(child_path)
            item = _make_item(child_path, name, child_size)
            if item:
                items.append(item)
        items.sort(key=lambda x: x["size"], reverse=True)

        if not items:
            item = _make_item(full_path, rel_path, total_bytes)
            if item:
                items.append(item)

        if items:
            groups.append({
                "label": rel_path,
                "path": full_path,
                "items": items[:MAX_ITEMS_PER_GROUP],
                "total_size": total_bytes,
                "total_size_formatted": format_size(total_bytes),
            })
    return groups


def _scan_downloads():
    """~/Downloads 스캔"""
    return _scan_simple_dir(os.path.join(HOME, "Downloads"), "Downloads", MIN_DOWNLOAD_MB)


def _scan_trash():
    """~/.Trash 스캔"""
    return _scan_simple_dir(os.path.join(HOME, ".Trash"), "휴지통 (.Trash)", MIN_TRASH_MB)


def _scan_media():
    """~/Movies, ~/Music 스캔"""
    groups = []
    groups.extend(_scan_simple_dir(os.path.join(HOME, "Movies"), "Movies", MIN_MEDIA_MB))
    groups.extend(_scan_simple_dir(os.path.join(HOME, "Music"), "Music", MIN_MEDIA_MB))
    return groups


def _scan_system_logs():
    """/var/log 스캔"""
    return _scan_simple_dir("/var/log", "시스템 로그 (/var/log)", MIN_LOG_MB)


# ============================================================
# 메인 스캔
# ============================================================

def scan_system():
    """카테고리별 병렬 스캔으로 시스템 전체 탐색"""
    scan_tasks = {
        "app_data": _scan_library,
        "dev_cache": _scan_dev_caches,
        "downloads": _scan_downloads,
        "trash": _scan_trash,
        "media": _scan_media,
        "system_logs": _scan_system_logs,
    }

    cat_results = {}
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fn): cat_id for cat_id, fn in scan_tasks.items()}
        for future in as_completed(futures):
            cat_id = futures[future]
            try:
                groups = future.result()
                for g in groups:
                    g["category"] = cat_id
                cat_results[cat_id] = groups
            except Exception:
                cat_results[cat_id] = []

    # 카테고리 순서대로 groups 병합
    all_groups = []
    categories = []
    for cat_id in CATEGORY_ORDER:
        groups = cat_results.get(cat_id, [])
        all_groups.extend(groups)
        cat_size = sum(g["total_size"] for g in groups)
        if cat_size > 0:
            categories.append({
                "id": cat_id,
                "name": CATEGORY_META[cat_id],
                "total_size": cat_size,
                "total_size_formatted": format_size(cat_size),
                "group_count": len(groups),
            })

    disk_info = get_disk_info()

    # Time Machine 스냅샷
    tm_count = 0
    try:
        result = subprocess.run(
            ["tmutil", "listlocalsnapshots", "/"],
            capture_output=True, text=True, timeout=10
        )
        tm_count = result.stdout.count("com.apple")
    except Exception:
        pass

    total_cleanable = sum(
        item["size"] for g in all_groups for item in g["items"]
    )

    return {
        "categories": categories,
        "groups": all_groups,
        "disk_info": disk_info,
        "tm_snapshots": tm_count,
        "total_cleanable": total_cleanable,
        "total_cleanable_formatted": format_size(total_cleanable),
    }


def scan_children(parent_path):
    """하위 폴더/파일 스캔 (드릴다운용) — du -d1 한 번으로 일괄 조회"""
    children = []
    try:
        entries = sorted(os.listdir(parent_path))
    except PermissionError:
        return [{"name": "(접근 권한 없음)", "path": parent_path, "size": 0,
                 "size_formatted": "N/A", "is_dir": False, "children_count": 0,
                 "description": "", "risk": "unknown"}]
    except Exception:
        return []

    sizes = get_children_sizes(parent_path)

    for entry in entries:
        full_path = os.path.join(parent_path, entry)
        try:
            if os.path.islink(full_path):
                continue
            is_dir = os.path.isdir(full_path)
            size = sizes.get(full_path, 0)
            if size == 0 and not is_dir:
                try:
                    size = os.path.getsize(full_path)
                except OSError:
                    continue
            if size < MIN_CHILD_BYTES:
                continue
            children_count = 0
            if is_dir:
                try:
                    children_count = len(os.listdir(full_path))
                except Exception:
                    pass
            desc, risk = get_folder_info(entry)
            children.append({
                "name": entry,
                "path": full_path,
                "size": size,
                "size_formatted": format_size(size),
                "is_dir": is_dir,
                "children_count": children_count,
                "description": desc,
                "risk": risk,
            })
        except Exception:
            continue

    children.sort(key=lambda x: x["size"], reverse=True)

    if len(children) > MAX_CHILDREN:
        rest_size = sum(c["size"] for c in children[MAX_CHILDREN:])
        rest_count = len(children) - MAX_CHILDREN
        children = children[:MAX_CHILDREN]
        children.append({
            "name": f"(기타 {rest_count}개 항목)",
            "path": "", "size": rest_size, "size_formatted": format_size(rest_size),
            "is_dir": False, "children_count": 0, "description": "", "risk": "unknown",
        })
    return children
