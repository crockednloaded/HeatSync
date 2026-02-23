#!/usr/bin/env bash
# HeatSync installer for Linux
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== HeatSync Installer ==="

# Create virtual environment
echo "[1/3] Creating Python virtual environment..."
if python3 -m venv .venv; then
    echo "      Virtual environment created at .venv/"
else
    echo "ERROR: Failed to create venv. Make sure python3-venv is installed."
    exit 1
fi

# Install dependencies
echo "[2/3] Installing dependencies..."
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements.txt -q
echo "      Dependencies installed."

# Autostart (KDE / GNOME / any XDG-compliant desktop)
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
