# macOS System Cleaner

**[한국어](#한국어) | [English](#english)**

---

## 한국어

macOS 시스템 데이터를 자동으로 스캔하고 불필요한 캐시/빌드 파일을 정리하는 도구입니다.

### 주요 기능

- 디스크 용량을 많이 차지하는 폴더 자동 탐색
- Xcode, Android Studio, Flutter, Homebrew 등 개발 도구 캐시 인식
- 폴더 드릴다운 (하위 폴더 무한 탐색)
- 안전도 표시 (안전/주의/위험)
- sudo 삭제 지원 (macOS 네이티브 비밀번호 입력)
- 병렬 스캔/드릴다운

### 실행 방법

#### 방법 1: Python으로 직접 실행

```bash
python3 run.py
```

브라우저에서 `http://localhost:8787` 이 자동으로 열립니다.

#### 방법 2: .app 번들로 빌드

```bash
chmod +x build_app.sh
./build_app.sh
```

빌드 후 `dist/System Cleaner.app`을 더블클릭하면 됩니다.

### 프로젝트 구조

```
mac-system-cleaner/
├── run.py                # 엔트리 포인트
├── build_app.sh          # .app 빌드 스크립트
├── .gitignore
├── README.md
└── app/
    ├── __init__.py
    ├── config.py          # 설정, 알려진 폴더 DB
    ├── scanner.py         # 파일 시스템 스캔
    ├── cleaner.py         # 파일 삭제 처리
    ├── server.py          # HTTP 서버 + API
    └── web/
        └── index.html     # 프론트엔드 (HTML/CSS/JS)
```

### 요구사항

- macOS 10.15+
- Python 3.8+
- 외부 패키지 불필요 (표준 라이브러리만 사용)
- .app 빌드 시 PyInstaller 필요 (빌드 스크립트가 자동 설치)

### 종료

- 터미널: `Ctrl+C`
- .app: 앱 종료

---

## English

A tool that automatically scans macOS system data and cleans up unnecessary cache and build files.

### Features

- Auto-detect large folders consuming disk space
- Recognizes dev tool caches: Xcode, Android Studio, Flutter, Homebrew, etc.
- Folder drill-down (infinite subfolder exploration)
- Safety indicators (safe / moderate / caution)
- sudo delete support (native macOS password prompt via osascript)
- Parallel scanning and drill-down

### Getting Started

#### Option 1: Run directly with Python

```bash
python3 run.py
```

Your browser will automatically open `http://localhost:8787`.

#### Option 2: Build as .app bundle

```bash
chmod +x build_app.sh
./build_app.sh
```

After building, double-click `dist/System Cleaner.app` to launch.

### Project Structure

```
mac-system-cleaner/
├── run.py                # Entry point
├── build_app.sh          # .app build script
├── .gitignore
├── README.md
└── app/
    ├── __init__.py
    ├── config.py          # Settings, known folders DB
    ├── scanner.py         # File system scanning
    ├── cleaner.py         # File deletion handling
    ├── server.py          # HTTP server + API
    └── web/
        └── index.html     # Frontend (HTML/CSS/JS)
```

### Requirements

- macOS 10.15+
- Python 3.8+
- No external packages required (stdlib only)
- PyInstaller needed for .app build (auto-installed by build script)

### Quit

- Terminal: `Ctrl+C`
- .app: Close the app
