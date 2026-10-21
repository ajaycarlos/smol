#!/usr/bin/env bash
# install.sh — Install smol via uv tool, run doctor, and configure integrations.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTO_YES=false
SKIP_INTEGRATE=false
SKIP_AUTOSTART=false

usage() {
    cat <<EOF
Usage: ./install.sh [OPTIONS]

Install smol as a CLI tool using uv, run system diagnostic check, and
optionally configure file manager integration and start-at-login autostart.

Options:
  -y, --yes          Answer yes to all interactive prompts (non-interactive)
  --no-integrate     Do not install file manager right-click integration
  --no-autostart     Do not install start-at-login autostart
  -h, --help         Show this help message and exit

Dependencies:
  Ghostscript (gs) and qpdf are required for PDF compression.
  If missing on Debian/Ubuntu/Mint:
    sudo apt install ghostscript qpdf libxcb-cursor0
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -y|--yes)
            AUTO_YES=true
            shift
            ;;
        --no-integrate)
            SKIP_INTEGRATE=true
            shift
            ;;
        --no-autostart)
            SKIP_AUTOSTART=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Run ./install.sh --help for usage." >&2
            exit 2
            ;;
    esac
done

echo "=== smol installer ==="

# 1. Check for uv
if ! command -v uv >/dev/null 2>&1; then
    echo "Error: 'uv' is required to install smol but was not found." >&2
    echo "Install uv via:" >&2
    echo "  curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
    echo "or:" >&2
    echo "  pip install uv" >&2
    exit 1
fi

# 2. Check for external tools (gs, qpdf) without bundling them
MISSING_TOOLS=()
if ! command -v gs >/dev/null 2>&1; then
    MISSING_TOOLS+=("ghostscript (gs)")
fi
if ! command -v qpdf >/dev/null 2>&1; then
    MISSING_TOOLS+=("qpdf")
fi

if [[ ${#MISSING_TOOLS[@]} -gt 0 ]]; then
    echo ""
    echo "Note: The following external PDF tools are not currently installed:"
    for tool in "${MISSING_TOOLS[@]}"; do
        echo "  - $tool"
    done
    echo "Image compression will work, but PDF compression requires Ghostscript and qpdf."
    echo "To install them on Debian/Ubuntu/Mint:"
    echo "  sudo apt install ghostscript qpdf libxcb-cursor0"
    echo ""
fi

# 3. Install smol via uv tool install
echo "Installing smol via uv tool install..."
uv tool install --force "$SCRIPT_DIR"

# 4. Locate installed binary
SMOL_BIN=""
if command -v smol >/dev/null 2>&1; then
    SMOL_BIN="$(command -v smol)"
elif [[ -x "$HOME/.local/bin/smol" ]]; then
    SMOL_BIN="$HOME/.local/bin/smol"
else
    echo "Error: smol executable not found after installation." >&2
    exit 1
fi

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo ""
    echo "Notice: $HOME/.local/bin is not in your current PATH."
    echo "Add it to your PATH by adding this line to ~/.bashrc or ~/.zshrc:"
    echo '  export PATH="$HOME/.local/bin:$PATH"'
    echo ""
fi

# 5. Run smol doctor
echo ""
echo "--- Running smol doctor ---"
"$SMOL_BIN" doctor || true
echo "---------------------------"
echo ""

prompt_yes_no() {
    local prompt="$1"
    local default_yes="${2:-true}"
    if [[ "$AUTO_YES" == true ]]; then
        return 0
    fi

    local hint="[Y/n]"
    if [[ "$default_yes" != true ]]; then
        hint="[y/N]"
    fi

    if [[ ! -t 0 ]]; then
        # Non-interactive stdin without --yes flag
        if [[ "$default_yes" == true ]]; then
            return 0
        else
            return 1
        fi
    fi

    read -r -p "$prompt $hint " response || return 1
    response="${response:-}"
    if [[ -z "$response" ]]; then
        if [[ "$default_yes" == true ]]; then
            return 0
        else
            return 1
        fi
    fi
    case "$response" in
        [yY][eE][sS]|[yY])
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

# 6. Offer right-click integration
if [[ "$SKIP_INTEGRATE" == false ]]; then
    if prompt_yes_no "Install right-click file manager integration?"; then
        echo "Installing right-click file manager integration..."
        "$SMOL_BIN" integrate install
    else
        echo "Skipping right-click integration. (You can run 'smol integrate install' later)"
    fi
else
    echo "Skipping right-click integration (--no-integrate)."
fi

# 7. Offer autostart (only on X11 sessions)
SESSION_TYPE="${XDG_SESSION_TYPE:-}"
if [[ "$SKIP_AUTOSTART" == false ]]; then
    if [[ "$SESSION_TYPE" == "wayland" ]]; then
        echo ""
        echo "Autostart skipped: Current session is Wayland."
        echo "smol's hold-key donut overlay requires an X11 session."
        echo "Right-click file manager actions and CLI work on any session."
    else
        if prompt_yes_no "Enable start-at-login autostart daemon (X11 hold-key donut)?"; then
            echo "Installing autostart entry..."
            "$SMOL_BIN" integrate autostart install
        else
            echo "Skipping autostart. (You can run 'smol integrate autostart install' later)"
        fi
    fi
else
    echo "Skipping autostart (--no-autostart)."
fi

# 8. Uninstallation instructions
echo ""
echo "=========================================================="
echo "smol installation finished successfully!"
echo ""
echo "To uninstall smol:"
echo "  $SCRIPT_DIR/uninstall.sh"
echo ""
echo "To uninstall and remove all configuration and log files:"
echo "  $SCRIPT_DIR/uninstall.sh --purge"
echo "=========================================================="
