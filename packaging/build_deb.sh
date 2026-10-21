#!/usr/bin/env bash
set -euo pipefail

# packaging/build_deb.sh — Build standalone .deb package for smol
# Reuses PyInstaller onedir payload at dist/smol/ (or builds it if missing)
# Produces dist/smol_<version>_amd64.deb

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

# Ensure PyInstaller onedir payload exists
if [[ ! -f "dist/smol/smol" ]]; then
    echo "dist/smol/smol not found; building with PyInstaller..."
    if command -v uv >/dev/null 2>&1; then
        PY_CMD="uv run"
    else
        PY_CMD="python3"
    fi
    ${PY_CMD} pyinstaller --distpath dist --workpath build --clean --noconfirm packaging/smol.spec
fi

if [[ ! -f "dist/smol/smol" ]]; then
    echo "ERROR: dist/smol/smol binary not found!" >&2
    exit 1
fi
echo "PyInstaller onedir payload verified at dist/smol/"

echo "=== 2. Staging Debian package layout ==="
STAGING_DIR="build/deb/smol_${VERSION}_amd64"
rm -rf "${STAGING_DIR}"

mkdir -p "${STAGING_DIR}/DEBIAN"
mkdir -p "${STAGING_DIR}/opt/smol"
mkdir -p "${STAGING_DIR}/usr/bin"
mkdir -p "${STAGING_DIR}/usr/share/applications"
mkdir -p "${STAGING_DIR}/usr/share/icons/hicolor"
mkdir -p "${STAGING_DIR}/usr/share/icons/hicolor/scalable/apps"

# 1. Copy application files to /opt/smol/
cp -a dist/smol/* "${STAGING_DIR}/opt/smol/"

# 2. Symlink /usr/bin/smol -> /opt/smol/smol
ln -s /opt/smol/smol "${STAGING_DIR}/usr/bin/smol"

# 3. Desktop entry
cp packaging/smol.desktop "${STAGING_DIR}/usr/share/applications/smol.desktop"

# 4. Application icons (PNG hierarchy + scalable SVG)
cp -a assets/icon/hicolor/* "${STAGING_DIR}/usr/share/icons/hicolor/"
cp assets/icon/smol.svg "${STAGING_DIR}/usr/share/icons/hicolor/scalable/apps/smol.svg"

echo "=== 3. Generating DEBIAN control, postinst, and postrm ==="
cat > "${STAGING_DIR}/DEBIAN/control" << EOF
Package: smol
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: amd64
Depends: ghostscript, qpdf, libxcb-cursor0, libx11-xcb1, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-randr0, libxcb-render-util0, libxcb-render0, libxcb-shape0, libxcb-shm0, libxcb-sync1, libxcb-xfixes0, libxcb-xkb1, libxcb1, libxkbcommon-x11-0, libxkbcommon0
Recommends: libnotify-bin
Maintainer: smol contributors <https://github.com/ajaycarlos/smol>
Description: Shrink any file to at most a chosen size
 smol is an offline desktop tool that shrinks images and PDF files
 to at most a chosen target size without uploading to remote servers.
EOF

cat > "${STAGING_DIR}/DEBIAN/postinst" << 'EOF'
#!/bin/sh
set -e

if [ "$1" = "configure" ]; then
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    fi
fi

exit 0
EOF

cat > "${STAGING_DIR}/DEBIAN/postrm" << 'EOF'
#!/bin/sh
set -e

if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    if command -v update-desktop-database >/dev/null 2>&1; then
        update-desktop-database -q /usr/share/applications || true
    fi
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
    fi
fi

exit 0
EOF

chmod 0755 "${STAGING_DIR}/DEBIAN/postinst"
chmod 0755 "${STAGING_DIR}/DEBIAN/postrm"

# Enforce clean standard file/directory permissions
find "${STAGING_DIR}/usr" "${STAGING_DIR}/opt" -type d -exec chmod 0755 {} +
find "${STAGING_DIR}/usr/share" -type f -exec chmod 0644 {} +
chmod 0755 "${STAGING_DIR}/opt/smol/smol"
chmod 0644 "${STAGING_DIR}/DEBIAN/control"

echo "=== 4. Building .deb with dpkg-deb ==="
OUTPUT_DEB="${REPO_ROOT}/dist/smol_${VERSION}_amd64.deb"
rm -f "${OUTPUT_DEB}"
dpkg-deb --build --root-owner-group "${STAGING_DIR}" "${OUTPUT_DEB}"

if [[ ! -f "${OUTPUT_DEB}" ]]; then
    echo "ERROR: Failed to create ${OUTPUT_DEB}" >&2
    exit 1
fi

echo "=== 5. Build Summary ==="
SIZE_BYTES=$(stat -c "%s" "${OUTPUT_DEB}")
SIZE_HUMAN=$(du -h "${OUTPUT_DEB}" | cut -f1)
echo "Output: ${OUTPUT_DEB}"
echo "Size: ${SIZE_HUMAN} (${SIZE_BYTES} bytes)"

if command -v lintian >/dev/null 2>&1; then
    echo "=== 6. Lintian check ==="
    lintian "${OUTPUT_DEB}" || true
else
    echo "=== 6. Lintian check: skipped (lintian not installed) ==="
fi
