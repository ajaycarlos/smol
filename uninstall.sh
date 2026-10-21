#!/usr/bin/env bash
# uninstall.sh — Remove smol CLI, file manager integration, and autostart.
set -euo pipefail

PURGE=false
AUTO_YES=false

usage() {
    cat <<EOF
Usage: ./uninstall.sh [OPTIONS]

Uninstall smol, remove file manager integrations, and disable autostart.
Keeps configuration files in ~/.config/smol unless --purge is specified.

Options:
  --purge     Remove all configuration, state, and cache files as well
  -y, --yes   Skip confirmation prompt
  -h, --help  Show this help message and exit
EOF
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --purge)
            PURGE=true
            shift
            ;;
        -y|--yes)
            AUTO_YES=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            echo "Unknown option: $1" >&2
            echo "Run ./uninstall.sh --help for usage." >&2
            exit 2
            ;;
    esac
done

echo "=== smol uninstaller ==="

# Confirmation prompt if interactive
if [[ "$AUTO_YES" == false && -t 0 ]]; then
    read -r -p "Are you sure you want to uninstall smol? [y/N] " confirm
    case "$confirm" in
        [yY][eE][sS]|[yY])
            ;;
        *)
            echo "Uninstallation cancelled."
            exit 0
            ;;
    esac
fi

# Locate smol executable if available
SMOL_BIN=""
if command -v smol >/dev/null 2>&1; then
    SMOL_BIN="$(command -v smol)"
elif [[ -x "$HOME/.local/bin/smol" ]]; then
    SMOL_BIN="$HOME/.local/bin/smol"
fi

# 1. Stop any running smol daemon
echo "Stopping any running daemon instances..."
if [[ -n "$SMOL_BIN" ]]; then
    "$SMOL_BIN" daemon stop >/dev/null 2>&1 || true
fi
pkill -f "smol daemon" >/dev/null 2>&1 || true

# 2. Remove autostart entry
echo "Removing autostart entry..."
if [[ -n "$SMOL_BIN" ]]; then
    "$SMOL_BIN" integrate autostart uninstall >/dev/null 2>&1 || true
fi
CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
rm -f "$CONFIG_HOME/autostart/smol.desktop"

# 3. Remove right-click file manager integrations
echo "Removing right-click file manager integrations..."
if [[ -n "$SMOL_BIN" ]]; then
    "$SMOL_BIN" integrate uninstall >/dev/null 2>&1 || true
fi

# Fallback direct cleanup of integration files
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
# Nemo
rm -f "$DATA_HOME/nemo/actions/smol_"*.nemo_action
# Nautilus
rm -f "$DATA_HOME/nautilus/scripts/smol_"*
# Dolphin / KDE
rm -f "$DATA_HOME/kservices5/ServiceMenus/smol_"*.desktop
rm -f "$DATA_HOME/kio/servicemenus/smol_"*.desktop

# 4. Uninstall smol CLI tool
echo "Uninstalling smol CLI tool..."
if command -v uv >/dev/null 2>&1; then
    uv tool uninstall smol >/dev/null 2>&1 || true
fi
rm -f "$HOME/.local/bin/smol"

# 5. Handle configuration, state, and cache
CONFIG_DIR="$CONFIG_HOME/smol"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/smol"
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/smol"

if [[ "$PURGE" == true ]]; then
    echo "Purging configuration, state, and cache directories..."
    rm -rf "$CONFIG_DIR" "$STATE_DIR" "$CACHE_DIR"
    echo "Purge complete: all configuration, logs, and caches removed."
else
    echo "Configuration preserved at: $CONFIG_DIR"
    echo "(To remove configuration and logs, re-run with --purge: ./uninstall.sh --purge)"
fi

echo "smol has been successfully uninstalled."
