#!/usr/bin/env bash
set -euo pipefail

# packaging/build_appimage.sh — Build standalone AppImage for smol
# Produces dist/smol/ (stable onedir for .deb reuse) and dist/smol-<version>-x86_64.AppImage

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

echo "=== 1. Checking build environment ==="
VERSION=$(python3 -c "
import tomllib
with open('pyproject.toml', 'rb') as f:
    print(tomllib.load(f)['project']['version'])
")
echo "smol version: ${VERSION}"

# Ensure uv / python virtualenv is ready
if command -v uv >/dev/null 2>&1; then
    PY_CMD="uv run"
else
    PY_CMD="python3"
fi

echo "=== 2. Building PyInstaller onedir payload (dist/smol/) ==="
${PY_CMD} pyinstaller --distpath dist --workpath build --clean --noconfirm packaging/smol.spec

if [[ ! -f "dist/smol/smol" ]]; then
    echo "ERROR: dist/smol/smol binary not found after PyInstaller build!" >&2
    exit 1
fi
echo "PyInstaller onedir build complete: dist/smol/ (preserved for .deb step)"

echo "=== 3. Assembling AppDir ==="
APPDIR="build/AppDir"
rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin"
mkdir -p "${APPDIR}/usr/share/applications"
mkdir -p "${APPDIR}/usr/share/icons/hicolor"

# Copy onedir payload to AppDir/usr/bin
cp -a dist/smol/* "${APPDIR}/usr/bin/"

# Copy desktop file
cp packaging/smol.desktop "${APPDIR}/smol.desktop"
cp packaging/smol.desktop "${APPDIR}/usr/share/applications/smol.desktop"

# Copy icons
cp assets/icon/smol.svg "${APPDIR}/smol.svg"
cp assets/icon/hicolor/256x256/apps/smol.png "${APPDIR}/smol.png"
ln -sf smol.png "${APPDIR}/.DirIcon"

cp -a assets/icon/hicolor/* "${APPDIR}/usr/share/icons/hicolor/"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/scalable/apps"
cp assets/icon/smol.svg "${APPDIR}/usr/share/icons/hicolor/scalable/apps/smol.svg"

# Create AppRun entrypoint
cat > "${APPDIR}/AppRun" << 'EOF'
#!/bin/sh
if [ -z "${APPDIR:-}" ]; then
    APPDIR="$(dirname "$(readlink -f "${0}")")"
fi
export PATH="$APPDIR/usr/bin:${PATH:-/usr/local/bin:/usr/bin:/bin}"
export XDG_DATA_DIRS="$APPDIR/usr/share:${XDG_DATA_DIRS:-/usr/local/share:/usr/share}"

if [ $# -eq 0 ]; then
    # When launched from GUI without terminal, default to donut
    if [ ! -t 1 ]; then
        exec "$APPDIR/usr/bin/smol" donut
    fi
fi
exec "$APPDIR/usr/bin/smol" "$@"
EOF
chmod +x "${APPDIR}/AppRun"

echo "=== 4. Resolving appimagetool ==="
APPIMAGETOOL=""
if command -v appimagetool >/dev/null 2>&1; then
    APPIMAGETOOL="$(command -v appimagetool)"
elif [[ -x "packaging/tools/appimagetool-x86_64.AppImage" ]]; then
    APPIMAGETOOL="${REPO_ROOT}/packaging/tools/appimagetool-x86_64.AppImage"
else
    mkdir -p packaging/tools
    echo "Downloading appimagetool..."
    curl -sL -o packaging/tools/appimagetool-x86_64.AppImage \
        "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x packaging/tools/appimagetool-x86_64.AppImage
    APPIMAGETOOL="${REPO_ROOT}/packaging/tools/appimagetool-x86_64.AppImage"
fi
echo "Using appimagetool: ${APPIMAGETOOL}"

echo "=== 5. Generating AppImage ==="
OUTPUT_APPIMAGE="${REPO_ROOT}/dist/smol-${VERSION}-x86_64.AppImage"
rm -f "${OUTPUT_APPIMAGE}"

ARCH=x86_64 "${APPIMAGETOOL}" "${APPDIR}" "${OUTPUT_APPIMAGE}" || \
ARCH=x86_64 "${APPIMAGETOOL}" --appimage-extract-and-run "${APPDIR}" "${OUTPUT_APPIMAGE}"

if [[ ! -f "${OUTPUT_APPIMAGE}" ]]; then
    echo "ERROR: Failed to create ${OUTPUT_APPIMAGE}" >&2
    exit 1
fi
chmod +x "${OUTPUT_APPIMAGE}"

echo "=== 6. Build Summary ==="
SIZE_BYTES=$(stat -c "%s" "${OUTPUT_APPIMAGE}")
SIZE_HUMAN=$(du -h "${OUTPUT_APPIMAGE}" | cut -f1)
echo "Output: ${OUTPUT_APPIMAGE}"
echo "Size: ${SIZE_HUMAN} (${SIZE_BYTES} bytes)"
echo "PyInstaller onedir preserved at: dist/smol/"
