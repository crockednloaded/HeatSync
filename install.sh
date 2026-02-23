#!/usr/bin/env bash
# HeatSync installer for Linux
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== HeatSync Installer ==="

# ── Python version check ───────────────────────────────────────────────────────
echo "[0/3] Checking Python version..."
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10 or later and retry."
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "ERROR: Python 3.10+ required (found $PY_VER)."
    echo "       Install a newer Python and retry."
    exit 1
fi
echo "      Python $PY_VER OK"

# ── Virtual environment ────────────────────────────────────────────────────────
echo "[1/3] Creating Python virtual environment..."
if ! python3 -m venv .venv 2>/dev/null; then
    echo "ERROR: Failed to create venv."
    # Detect distro and give a targeted fix hint
    if command -v apt-get &>/dev/null; then
        echo "       On Debian/Ubuntu, run:"
        echo "         sudo apt-get install python3-venv python3-pip"
        echo "       Then re-run this script."
    elif command -v dnf &>/dev/null; then
        echo "       On Fedora/RHEL, run:"
        echo "         sudo dnf install python3"
    elif command -v pacman &>/dev/null; then
        echo "       On Arch, Python ships with venv — reinstall python:"
        echo "         sudo pacman -S python"
    fi
    exit 1
fi
echo "      Virtual environment created at .venv/"

# ── Dependencies ───────────────────────────────────────────────────────────────
echo "[2/3] Installing dependencies..."
.venv/bin/pip install --upgrade pip -q
if ! .venv/bin/pip install -r requirements.txt -q; then
    echo "ERROR: pip install failed."
    echo "       This usually means missing system libraries for PyQt6."
    if command -v apt-get &>/dev/null; then
        echo "       Try: sudo apt-get install libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 libxkbcommon-x11-0"
    elif command -v dnf &>/dev/null; then
        echo "       Try: sudo dnf install libxcb libxkbcommon-x11"
    elif command -v pacman &>/dev/null; then
        echo "       Try: sudo pacman -S libxcb libxkbcommon-x11"
    fi
    exit 1
fi
echo "      Dependencies installed."

# ── Autostart (XDG-compliant: KDE, GNOME, Cinnamon, MATE, LXQt, ...) ──────────
echo "[3/3] Setting up autostart..."
AUTOSTART_DIR="$HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"
PYTHON_PATH="$SCRIPT_DIR/.venv/bin/python"
SCRIPT_PATH="$SCRIPT_DIR/HeatSync.py"

cat > "$AUTOSTART_DIR/heatsync.desktop" << EOF
[Desktop Entry]
Type=Application
Name=HeatSync
Comment=Real-time system monitor
Exec=$PYTHON_PATH $SCRIPT_PATH
Icon=utilities-system-monitor
Terminal=false
Hidden=false
X-GNOME-Autostart-enabled=true
EOF

echo "      Autostart entry created: $AUTOSTART_DIR/heatsync.desktop"

echo ""
echo "=== Done! ==="
echo "Run HeatSync with:  bash run.sh"
echo "Or directly:        .venv/bin/python HeatSync.py"
