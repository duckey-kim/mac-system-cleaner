"""HTTP 서버 모듈 — API 핸들러 및 서버 시작"""

import http.server
import json
import os
import socket
import socketserver
import sys
import threading
import webbrowser

from urllib.parse import parse_qs, urlparse, unquote

from .config import HOME, PORT, VERSION, reload_folders
from .scanner import scan_system, scan_children
from .cleaner import delete_path
from .lookup import lookup_folder
from .updater import check_update, get_cached_result, check_update_background, do_update, get_download_status


def _load_html():
    """HTML 템플릿 로드 (PyInstaller 번들 호환)"""
    if getattr(sys, "frozen", False):
        # PyInstaller: --add-data "app/web/index.html:app/web" → _MEIPASS/app/web/
        html_path = os.path.join(sys._MEIPASS, "app", "web", "index.html")
    else:
        base = os.path.dirname(os.path.abspath(__file__))
        html_path = os.path.join(base, "web", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return f.read()


# 서버 시작 시 한 번만 로드
_HTML_CACHE = None


def _get_html():
    global _HTML_CACHE
    if _HTML_CACHE is None:
        _HTML_CACHE = _load_html()
    return _HTML_CACHE


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 로그 출력 끄기

    def handle(self):
        """BrokenPipeError 무시 (브라우저가 응답 전에 연결 끊은 경우)"""
        try:
            super().handle()
        except BrokenPipeError:
            pass

    def do_HEAD(self):
        """heartbeat용 — 서버 살아있는지 확인"""
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        p = urlparse(self.path)
        if p.path in ("/", "/index.html"):
            self._ok("text/html", _get_html())
        elif p.path == "/api/scan":
            reload_folders()  # 검색된 폴더 정보 반영
            self._json(scan_system())
        elif p.path == "/api/children":
            qs = parse_qs(p.query)
            target = unquote(qs.get("path", [""])[0])
            if not target or (not target.startswith(HOME) and not target.startswith("/var/")):
                self._json({"children": [], "error": "허용되지 않는 경로"})
            else:
                self._json({"children": scan_children(target), "path": target})
        elif p.path == "/api/lookup":
            qs = parse_qs(p.query)
            name = unquote(qs.get("name", [""])[0])
            folder_path = unquote(qs.get("path", [""])[0])
            if not name:
                self._json({"error": "name 필요"})
            else:
                result = lookup_folder(name, folder_path)
                self._json(result)
        elif p.path == "/api/check-update":
            result = get_cached_result()
            if not result.get("checked"):
                result = check_update()
            self._json(result)
        elif p.path == "/api/update-status":
            self._json(get_download_status())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/do-update":
            # 백그라운드에서 업데이트 실행
            def _run():
                do_update()
            t = threading.Thread(target=_run, daemon=True)
            t.start()
            self._json({"started": True, "message": "업데이트 시작됨"})
        elif self.path == "/api/delete":
            body = self.rfile.read(int(self.headers["Content-Length"]))
            data = json.loads(body)
            p = data.get("path", "")
            recreate = data.get("recreate", False)
            use_sudo = data.get("use_sudo", False)
            if not p.startswith(HOME) and not p.startswith("/var/log"):
                self._json({"success": False, "code": "blocked", "message": "보안: 허용되지 않는 경로"})
            else:
                ok, code, msg = delete_path(p, recreate, use_sudo)
                self._json({"success": ok, "code": code, "message": msg})
        else:
            self.send_response(404)
            self.end_headers()

    def _ok(self, ct, body):
        self.send_response(200)
        self.send_header("Content-Type", ct + "; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8") if isinstance(body, str) else body)

    def _json(self, obj):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))


def find_free_port(start=PORT, end=None):
    """사용 가능한 포트 찾기 (이미 실행 중일 때 충돌 방지)"""
    if end is None:
        end = start + 20
    for port in range(start, end):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("", port))
                return port
        except OSError:
            continue
    return start


def main():
    """서버 시작"""
    port = find_free_port()

    print(f"""
 ╔════════════════════════════════════════════════════════╗
 ║           macOS System Cleaner v3.2                    ║
 ║                                                        ║
 ║   자동 스캔 — 개발 도구 사전 입력 불필요               ║
 ║   브라우저: http://localhost:{port}                       ║
 ║   종료: Ctrl+C 또는 앱 종료                            ║
 ╚════════════════════════════════════════════════════════╝
""")

    # ThreadingTCPServer: 각 요청을 별도 스레드로 처리 → 드릴다운 병렬 실행 가능
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    httpd = socketserver.ThreadingTCPServer(("", port), Handler)

    # 서버를 별도 데몬 스레드에서 실행
    server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    server_thread.start()

    # 백그라운드 업데이트 확인 (5초 후)
    check_update_background(delay=5)

    # 브라우저 자동 열기
    threading.Timer(0.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()

    # 메인 스레드에서 Ctrl+C 대기
    try:
        while server_thread.is_alive():
            server_thread.join(timeout=1.0)
    except KeyboardInterrupt:
        print("\n종료합니다...")
        httpd.server_close()
        print("서버가 종료되었습니다.")
        os._exit(0)
