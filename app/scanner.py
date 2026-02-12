"""파일 시스템 스캔 모듈 — 큰 폴더 자동 탐색"""

import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import HOME, get_folder_info


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


def get_dir_size(path):
    """디렉토리 크기를 바이트로 반환 (du -sk 사용) — 단일 폴더용"""
    try:
        result = subprocess.run(
            ["du", "-sk", path],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            return int(result.stdout.split()[0]) * 1024
    except Exception:
        pass
    return 0


def get_children_sizes(parent_path):
    """du -d1 -k 로 하위 폴더 크기를 한 번에 가져오기 (핵심 최적화)"""
    sizes = {}
    try:
        result = subprocess.run(
            ["du", "-d1", "-k", parent_path],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode in (0, 1):  # 1 = 일부 권한 오류 (무시)
            for line in result.stdout.strip().split("\n"):
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    try:
                        kb = int(parts[0])
                        p = parts[1]
                        if p != parent_path:
                            sizes[p] = kb * 1024
                    except ValueError:
                        continue
    except Exception:
        pass
    return sizes


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


def scan_top_folders(base_path, min_size_mb=50):
    """base_path의 직속 하위 폴더를 크기 순으로 반환 (du -d1 한 번으로 일괄 조회)"""
    results = []
    min_bytes = min_size_mb * 1024 * 1024

    sizes = get_children_sizes(base_path)

    try:
        entries = os.listdir(base_path)
    except (PermissionError, OSError):
        return results

    for entry in entries:
        full_path = os.path.join(base_path, entry)
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

            if size < min_bytes:
                continue

            children_count = 0
            if is_dir:
                try:
                    children_count = len(os.listdir(full_path))
                except Exception:
                    pass

            desc, risk = get_folder_info(entry)
            results.append({
                "name": entry,
                "path": full_path,
                "size": size,
                "size_formatted": format_size(size),
                "is_dir": is_dir,
                "children_count": children_count,
                "description": desc,
                "risk": risk,
                "drillable": is_dir and children_count > 0,
            })
        except Exception:
            continue

    results.sort(key=lambda x: x["size"], reverse=True)
    return results


def scan_system():
    """시스템 자동 스캔 — 주요 경로의 큰 폴더를 병렬로 탐색"""
    scan_roots = [
        {"label": "홈 디렉토리", "path": HOME, "min_mb": 100},
        {"label": "Library", "path": os.path.join(HOME, "Library"), "min_mb": 50},
        {"label": "Library/Caches", "path": os.path.join(HOME, "Library", "Caches"), "min_mb": 30},
        {"label": "Library/Developer", "path": os.path.join(HOME, "Library", "Developer"), "min_mb": 30},
        {"label": "Library/Application Support", "path": os.path.join(HOME, "Library", "Application Support"), "min_mb": 50},
        {"label": "Library/Containers", "path": os.path.join(HOME, "Library", "Containers"), "min_mb": 50},
    ]

    def scan_one(root):
        if not os.path.isdir(root["path"]):
            return None
        items = scan_top_folders(root["path"], min_size_mb=root["min_mb"])
        return {"root": root, "items": items}

    groups = []
    all_paths_seen = set()

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(scan_one, r): r for r in scan_roots}
        results_map = {}
        for future in as_completed(futures):
            root = futures[future]
            results_map[root["label"]] = future.result()

    for root in scan_roots:
        result = results_map.get(root["label"])
        if not result:
            continue
        filtered = []
        for item in result["items"]:
            if item["path"] not in all_paths_seen:
                filtered.append(item)
                all_paths_seen.add(item["path"])
        if filtered:
            total_size = sum(it["size"] for it in filtered)
            groups.append({
                "label": root["label"],
                "path": root["path"],
                "items": filtered[:20],
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
            if size < 512 * 1024:
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

    if len(children) > 30:
        rest_size = sum(c["size"] for c in children[30:])
        rest_count = len(children) - 30
        children = children[:30]
        children.append({
            "name": f"(기타 {rest_count}개 항목)",
            "path": "", "size": rest_size, "size_formatted": format_size(rest_size),
            "is_dir": False, "children_count": 0, "description": "", "risk": "unknown",
        })
    return children
