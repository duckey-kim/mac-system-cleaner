"""파일 시스템 스캔 모듈 — du -d2 단일 호출로 ~/Library 전체 탐색"""

import os
import shutil
import subprocess

from .config import HOME, get_folder_info

# ============================================================
# 스캔 임계값 상수
# ============================================================
MIN_GROUP_MB = 50       # depth-1 그룹 최소 크기
MIN_ITEM_MB = 20        # depth-2 항목 최소 크기
MIN_CHILD_BYTES = 512 * 1024   # drill-down 항목 최소 크기 (512KB)
MAX_ITEMS_PER_GROUP = 20       # 그룹당 최대 항목 수
MAX_CHILDREN = 30              # drill-down 최대 항목 수
DU_TIMEOUT = 120               # du 명령 타임아웃 (초)


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


def scan_system():
    """시스템 자동 스캔 — du -d2 한 번으로 ~/Library 전체 탐색 (하드코딩 없음)"""
    library_path = os.path.join(HOME, "Library")
    min_group_bytes = MIN_GROUP_MB * 1024 * 1024
    min_item_bytes = MIN_ITEM_MB * 1024 * 1024

    # ---- 1) du -d2 단일 호출로 전체 크기 수집 ----
    all_sizes = {}
    try:
        result = subprocess.run(
            ["du", "-d2", "-k", library_path],
            capture_output=True, text=True, timeout=DU_TIMEOUT
        )
        if result.returncode in (0, 1):  # 1 = 일부 경로 권한 오류 (무시 가능)
            all_sizes = _parse_du(result.stdout, library_path)
    except Exception:
        pass

    # ---- 2) depth-1 / depth-2 분류 ----
    d1_sizes = {}          # d1_path -> size
    d2_by_parent = {}      # d1_path -> [(d2_path, size, name)]

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

    # ---- 3) 그룹 구성: depth-1별로 depth-2 항목 묶기 ----
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

        # depth-2 항목이 없으면 depth-1 폴더 자체를 drillable 항목으로
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
        item["size"] for g in groups for item in g["items"]
    )

    return {
        "groups": groups,
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
