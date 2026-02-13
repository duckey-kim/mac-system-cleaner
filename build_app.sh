#!/bin/bash
# ============================================================
# macOS System Cleaner — .app 빌드 스크립트
# ============================================================
# 프로젝트 루트에서 실행:
#   chmod +x build_app.sh
#   ./build_app.sh
#
# 완료 후 "System Cleaner.app"이 생성됩니다.
# ============================================================

set -e

APP_NAME="System Cleaner"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║     macOS System Cleaner — App 빌드 스크립트       ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""

# 1) 프로젝트 구조 확인
if [ ! -f "$SCRIPT_DIR/run.py" ]; then
    echo "❌ 오류: run.py를 찾을 수 없습니다."
    echo "   이 스크립트를 프로젝트 루트에서 실행하세요."
    exit 1
fi

if [ ! -d "$SCRIPT_DIR/app" ]; then
    echo "❌ 오류: app/ 디렉토리를 찾을 수 없습니다."
    exit 1
fi

# 2) Python3 확인
if ! command -v python3 &>/dev/null; then
    echo "❌ 오류: python3이 설치되어 있지 않습니다."
    exit 1
fi

echo "✅ python3 확인: $(python3 --version)"

# 3) PyInstaller 설치 확인/설치
echo ""
echo "📦 PyInstaller 확인 중..."
if ! python3 -m PyInstaller --version &>/dev/null 2>&1; then
    echo "   PyInstaller가 없습니다. 설치합니다..."
    pip3 install pyinstaller --break-system-packages 2>/dev/null || pip3 install pyinstaller
    echo "   ✅ PyInstaller 설치 완료"
else
    echo "   ✅ PyInstaller 이미 설치됨: $(python3 -m PyInstaller --version 2>&1)"
fi

# 4) 앱 아이콘 생성
echo ""
echo "🎨 앱 아이콘 생성 중..."

ICONSET_DIR="$SCRIPT_DIR/AppIcon.iconset"
mkdir -p "$ICONSET_DIR"

python3 << 'ICONPY'
import struct, zlib, os

def create_icon_png(size, path):
    pixels = []
    cx, cy = size // 2, size // 2
    r = size // 2

    for y in range(size):
        row = []
        for x in range(size):
            dx, dy = x - cx, y - cy
            dist = (dx*dx + dy*dy) ** 0.5

            if dist > r:
                row.extend([0, 0, 0, 0])
            else:
                t = y / size
                br = int(30 + 60 * t)
                bg = int(80 + 40 * (1 - t))
                bb = int(200 - 50 * t)

                if abs(x - cx) < size * 0.04 and cy - size * 0.3 < y < cy + size * 0.1:
                    br, bg, bb = 200, 180, 140
                elif cy + size * 0.05 < y < cy + size * 0.3:
                    bw = int((y - cy - size * 0.05) * 0.8)
                    if abs(x - cx) < bw:
                        br, bg, bb = 180, 160, 120

                if dist > r - 2:
                    alpha = max(0, min(255, int((r - dist) * 128)))
                else:
                    alpha = 255

                row.extend([br, bg, bb, alpha])
        pixels.append(bytes(row))

    def make_png(w, h, rows):
        def chunk(ctype, data):
            c = ctype + data
            return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)

        sig = b'\x89PNG\r\n\x1a\n'
        ihdr = chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 6, 0, 0, 0))
        raw = b''
        for row in rows:
            raw += b'\x00' + row
        idat = chunk(b'IDAT', zlib.compress(raw))
        iend = chunk(b'IEND', b'')
        return sig + ihdr + idat + iend

    with open(path, 'wb') as f:
        f.write(make_png(size, size, pixels))

script_dir = os.environ.get('SCRIPT_DIR', os.path.dirname(os.path.abspath(__file__)))
iconset = os.path.join(script_dir, 'AppIcon.iconset')

for size, name in [
    (16, 'icon_16x16.png'), (32, 'icon_16x16@2x.png'),
    (32, 'icon_32x32.png'), (64, 'icon_32x32@2x.png'),
    (128, 'icon_128x128.png'), (256, 'icon_128x128@2x.png'),
    (256, 'icon_256x256.png'), (512, 'icon_256x256@2x.png'),
    (512, 'icon_512x512.png'), (1024, 'icon_512x512@2x.png'),
]:
    create_icon_png(size, os.path.join(iconset, name))

print("  아이콘 PNG 생성 완료")
ICONPY

ICNS_PATH="$SCRIPT_DIR/AppIcon.icns"
if iconutil -c icns "$ICONSET_DIR" -o "$ICNS_PATH" 2>/dev/null; then
    echo "   ✅ AppIcon.icns 생성 완료"
    ICON_OPT="--icon=$ICNS_PATH"
else
    echo "   ⚠️  icns 변환 실패 — 기본 아이콘 사용"
    ICON_OPT=""
fi

# 5) 버전 추출 (git tag → VERSION 파일)
echo ""
echo "🏷️  버전 추출 중..."
GIT_VERSION=$(git describe --tags --abbrev=0 2>/dev/null | sed 's/^v//')
if [ -z "$GIT_VERSION" ]; then
    GIT_VERSION="dev"
    echo "   ⚠️  git tag 없음 — VERSION=dev"
else
    echo "   ✅ VERSION=$GIT_VERSION (git tag)"
fi
echo "$GIT_VERSION" > "$SCRIPT_DIR/VERSION"

# 6) PyInstaller로 .app 빌드
echo ""
echo "🔨 앱 빌드 중... (1~2분 소요)"
echo ""

cd "$SCRIPT_DIR"

python3 -m PyInstaller \
    --onefile \
    --windowed \
    --name "$APP_NAME" \
    --noconfirm \
    --clean \
    $ICON_OPT \
    --osx-bundle-identifier "com.syscleaner.macos" \
    --add-data "app/web/index.html:app/web" \
    --add-data "app/learned_folders.json:app" \
    --add-data "VERSION:." \
    run.py

# 7) 결과 확인
APP_PATH="$SCRIPT_DIR/dist/$APP_NAME.app"

if [ -d "$APP_PATH" ]; then
    echo ""
    echo "╔════════════════════════════════════════════════════╗"
    echo "║  ✅ 빌드 성공!                                     ║"
    echo "╠════════════════════════════════════════════════════╣"
    echo "║                                                    ║"
    echo "║  📍 위치: dist/System Cleaner.app                  ║"
    echo "║                                                    ║"
    echo "║  실행 방법:                                        ║"
    echo "║  1. Finder에서 dist 폴더 열기                      ║"
    echo "║  2. 'System Cleaner' 더블클릭                      ║"
    echo "║                                                    ║"
    echo "║  💡 Applications 폴더로 드래그하면                   ║"
    echo "║     Launchpad에서도 실행 가능!                      ║"
    echo "║                                                    ║"
    echo "╚════════════════════════════════════════════════════╝"
    echo ""

    read -p "📂 Applications 폴더에 복사할까요? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        rm -rf "/Applications/$APP_NAME.app" 2>/dev/null
        cp -R "$APP_PATH" "/Applications/$APP_NAME.app"
        echo "✅ /Applications/$APP_NAME.app 으로 복사 완료!"
        echo "   Launchpad 또는 Spotlight에서 'System Cleaner' 검색하세요."
    fi

    open "$SCRIPT_DIR/dist"
else
    echo ""
    echo "❌ 빌드 실패. 위 오류 메시지를 확인하세요."
    exit 1
fi

# 8) 정리
echo ""
echo "🧹 임시 파일 정리 중..."
rm -rf "$SCRIPT_DIR/build" "$SCRIPT_DIR/$APP_NAME.spec" "$ICONSET_DIR" "$ICNS_PATH" "$SCRIPT_DIR/VERSION" 2>/dev/null
echo "✅ 정리 완료"
echo ""
echo "🎉 끝! 이제 'System Cleaner' 앱을 더블클릭해서 사용하세요."
