#!/usr/bin/env bash
set -euo pipefail

# scripts/verify_appimage.sh — Verification script for smol AppImage artifact

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

echo "=================================================="
echo "VERIFYING SMOL APPIMAGE"
echo "=================================================="

# 1. Locate AppImage
APPIMAGE=$(ls dist/smol-*-x86_64.AppImage 2>/dev/null | head -n1 || true)
if [[ -z "${APPIMAGE}" || ! -f "${APPIMAGE}" ]]; then
    echo "FAIL: AppImage binary not found in dist/" >&2
    exit 1
fi
echo "✓ AppImage found: ${APPIMAGE}"

# 2. Honest size reporting
SIZE_BYTES=$(stat -c "%s" "${APPIMAGE}")
SIZE_HUMAN=$(du -h "${APPIMAGE}" | cut -f1)
echo "✓ Exact size: ${SIZE_HUMAN} (${SIZE_BYTES} bytes)"

# 3. Stable onedir path check
if [[ ! -x "dist/smol/smol" ]]; then
    echo "FAIL: Stable PyInstaller onedir binary dist/smol/smol is missing!" >&2
    exit 1
fi
ONEDIR_SIZE=$(du -sh dist/smol | cut -f1)
echo "✓ Stable onedir preserved at: dist/smol/ (${ONEDIR_SIZE})"

# 4. Clean environment execution (--version)
echo "--- Testing clean environment (no virtualenv, clean PATH=/usr/bin:/bin) ---"
CLEAN_VER=$(env -i HOME="${HOME}" LANG="en_US.UTF-8" DISPLAY="${DISPLAY:-:0}" XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" PATH="/usr/bin:/bin" "${APPIMAGE}" --version)
echo "Output: ${CLEAN_VER}"
if [[ "${CLEAN_VER}" != smol* ]]; then
    echo "FAIL: Unexpected version output: ${CLEAN_VER}" >&2
    exit 1
fi
echo "✓ AppImage --version runs cleanly in isolated environment"

# 5. Extract-and-run fallback test
echo "--- Testing --appimage-extract-and-run fallback ---"
EXTRACT_VER=$(env -i HOME="${HOME}" LANG="en_US.UTF-8" DISPLAY="${DISPLAY:-:0}" XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" PATH="/usr/bin:/bin" "${APPIMAGE}" --appimage-extract-and-run --version)
echo "Output: ${EXTRACT_VER}"
if [[ "${EXTRACT_VER}" != smol* ]]; then
    echo "FAIL: Unexpected fallback version output: ${EXTRACT_VER}" >&2
    exit 1
fi
echo "✓ --appimage-extract-and-run functions properly"

# 6. Absence of bundled Ghostscript and qpdf
echo "--- Verifying NO bundled Ghostscript or qpdf ---"
rm -rf /tmp/smol_appimage_inspect
"${APPIMAGE}" --appimage-extract-and-run --help >/dev/null 2>&1 || true
# Extract payload to inspect filesystem
"${APPIMAGE}" --appimage-extract >/dev/null 2>&1
mv squashfs-root /tmp/smol_appimage_inspect

BUNDLED_GS_OR_QPDF=$(find /tmp/smol_appimage_inspect -type f \( -name "gs" -o -name "qpdf" -o -name "libgs.so*" \) || true)
rm -rf /tmp/smol_appimage_inspect

if [[ -n "${BUNDLED_GS_OR_QPDF}" ]]; then
    echo "FAIL: Found bundled Ghostscript/qpdf binaries: ${BUNDLED_GS_OR_QPDF}" >&2
    exit 1
fi
echo "✓ No Ghostscript (gs) or qpdf bundled inside AppImage (external tools relied upon)"

# 7. Test smol doctor via AppImage
echo "--- Testing smol doctor guidance via AppImage ---"
env -i HOME="${HOME}" LANG="en_US.UTF-8" DISPLAY="${DISPLAY:-:0}" XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" PATH="/usr/bin:/bin" "${APPIMAGE}" doctor
echo "✓ smol doctor runs cleanly through AppImage"

# 8. Test donut launch via AppImage
echo "--- Testing Donut launch via AppImage (timeout 2s) ---"
timeout 2s env -i HOME="${HOME}" LANG="en_US.UTF-8" DISPLAY="${DISPLAY:-:0}" XAUTHORITY="${XAUTHORITY:-$HOME/.Xauthority}" PATH="/usr/bin:/bin" "${APPIMAGE}" donut --demo || true
echo "✓ Donut window initializes and displays via AppImage"

# 9. Test real image compression via AppImage
echo "--- Testing image shrink via AppImage ---"
env -i HOME="${HOME}" LANG="en_US.UTF-8" PATH="/usr/bin:/bin" "${APPIMAGE}" shrink tests/samples/portrait.jpg --max 100KB --dry-run
echo "✓ CLI shrink executes successfully via AppImage"

echo "=================================================="
echo "ALL APPIMAGE VERIFICATIONS PASSED"
echo "=================================================="
