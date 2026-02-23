# CLAUDE.ko.md

이 파일은 사람이 읽기 위한 한국어 프로젝트 가이드입니다.
Claude Code용 영문 원본: [CLAUDE.md](CLAUDE.md)

## 개요

macOS System Cleaner — macOS 디스크의 불필요한 캐시/빌드 파일을 자동 스캔하고 정리하는 도구.
버전은 git tag 기반 단일 진실 공급원 (`app/config.py:_get_version()`).
Python 표준 라이브러리만 사용 (외부 의존성 없음). 프론트엔드는 바닐라 JS 단일 파일 SPA.

## 명령어

```bash
python3 run.py          # 개발 실행 (localhost:8787 자동 오픈)
./build_app.sh          # .app 빌드 (PyInstaller, 스크립트가 자동 설치)
python3 -m pytest tests/ # 테스트 실행 (unittest 기반, 외부 의존성 없음)
```

테스트는 `tests/` 디렉토리에 위치 (unittest 기반). 빌드 검증은 `./build_app.sh` 실행으로 확인.

## Git Workflow

- 브랜치 모델: git flow (feature -> develop -> release -> main + tag)
- 작업 브랜치: `develop`
- 버전 태그는 `main` 브랜치에서만

## 주요 기능

- 카테고리별 시스템 전체 스캔: ~/Library, 개발자 캐시, 다운로드, 휴지통, 미디어, 시스템 로그를 병렬로 탐색
- 드릴다운: 폴더 클릭으로 하위 파일 무한 탐색
- 일괄/개별 삭제: 체크박스 선택 후 일괄 삭제 또는 개별 삭제
- sudo 지원: 권한 필요 시 macOS 네이티브 비밀번호 창으로 관리자 인증
- Time Machine 스냅샷 관리: 로컬 TM 스냅샷 조회/삭제
- 안전 항목 원클릭 정리: risk=safe 항목 일괄 삭제
- 삭제 이력: 삭제 작업 기록 및 통계 조회
- 자동 업데이트: GitHub Releases 기반 최신 버전 확인 및 업데이트

## 핵심 규칙

- `sys.frozen` 분기: PyInstaller 번들에서 리소스 경로가 `sys._MEIPASS` 기준으로 변경됨. config.py, server.py에 해당 로직 존재
- 경로 보안: 삭제/조회 API는 `HOME` 또는 `/var/log` 시작 경로만 허용
- `learned_folders.json`의 키는 반드시 소문자 폴더명, 값은 `{desc, risk}` 구조
- 프론트엔드는 `app/web/index.html` 단일 파일 (별도 빌드 없음)
- sudo 2단계 패턴: `sudo -n` (캐시) -> `osascript` (GUI 비밀번호 창) — cleaner.py, tm_manager.py에서 사용
- 삭제 이력: `~/.mac_cleaner_history.json`에 FIFO 500건 저장, thread-safe (threading.Lock)

## 문서 관리 규칙

**feature 또는 hotfix 브랜치 작업 완료 시, 최종 커밋 전에 반드시 `.claude-context/` 문서를 업데이트해야 합니다.**

체크리스트:
1. API endpoint 추가/변경 시 → `architecture.json`의 `api` 섹션 업데이트
2. 새 컴포넌트/파일 생성 시 → `architecture.json`의 `components` 섹션 업데이트
3. 새로운 코딩 패턴이나 주의사항 발견 시 → `conventions.json` 업데이트
4. 빌드 프로세스 변경 시 → `architecture.json`의 `build` 섹션 업데이트
5. 버전 변경 시 → `architecture.json` 및 `CLAUDE.md` Overview 업데이트
6. 이 파일(`CLAUDE.ko.md`)도 동일하게 반영

## 상세 컨텍스트

아키텍처, API 스펙, 컴포넌트 관계, 코딩 규칙은 구조화된 JSON으로 관리:

- [.claude-context/architecture.json](.claude-context/architecture.json) — 컴포넌트, API 라우트, 데이터 흐름, 빌드 설정
- [.claude-context/conventions.json](.claude-context/conventions.json) — 코딩 패턴, 주의사항, 설계 결정
