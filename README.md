# HeatSync

**Real-time system monitor for Linux, Windows & macOS**

A dark-themed, frameless desktop widget built with PyQt6. Circular arc gauges, sparkline history graphs, and a live status bar with vendor-aware hardware labels. Sits in your system tray and stays out of your way.

---

![HeatSync](assets/screenshot.png)

---

## Download

| Platform | Download | |
|---|---|---|
| **Linux** | [HeatSync.AppImage](https://github.com/crockednloaded/HeatSync/releases/latest) | Works on any distro |
| **Linux (Arch)** | `yay -S heatsync-bin` | AUR package |
| **Windows** | [HeatSync.exe](https://github.com/crockednloaded/HeatSync/releases/latest) | No install needed |
| **macOS** | [HeatSync.dmg](https://github.com/crockednloaded/HeatSync/releases/latest) | Drag to Applications |

---

## Features

- **Circular arc gauges** — 300° sweep per metric; color shifts white → orange → red with load
- **Sparkline history** — 90-point rolling graph per metric
- **Vendor-aware labels** — AMD, NVIDIA, and Intel names color-coded in the title bar
- **Status bar** — RAM, VRAM, CPU frequency, thread count, and disk usage
- **Dock mode** — snaps to the top edge as a full-width bar; double-click to toggle
- **Window memory** — remembers position, size, and dock state between sessions
- **System tray** — no taskbar icon; hides to tray on close
- **GPU auto-detection** — NVIDIA via pynvml; AMD and Intel via sysfs (no extra drivers needed)
- **Intel CPU temperature** — via `coretemp` kernel driver, works out of the box

---

## Installation

### Linux

**AppImage** — recommended, works on any distro (Ubuntu 18.04+, Fedora 32+, Arch, etc.):

```bash
chmod +x HeatSync.AppImage
./HeatSync.AppImage
```

**Arch Linux / AUR:**

```bash
yay -S heatsync-bin
```

**From source:**

```bash
git clone https://github.com/crockednloaded/HeatSync.git
cd HeatSync
bash install.sh
```

`install.sh` creates a `.venv`, installs dependencies, and sets up autostart.

### Windows

Download **[HeatSync.exe](https://github.com/crockednloaded/HeatSync/releases/latest)** and run it — no installation required.

> CPU temperature on Windows requires [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) running in the background.

### macOS

Download **[HeatSync.dmg](https://github.com/crockednloaded/HeatSync/releases/latest)**, open it, and drag HeatSync.app to your Applications folder.

---

## GPU Support

| GPU | Driver | Notes |
|-----|--------|-------|
| NVIDIA | pynvml | Requires `nvidia-utils` |
| AMD | amdgpu sysfs | No extra drivers |
| Intel Arc / iGPU | xe / i915 sysfs | No extra drivers |

When multiple GPUs are present, priority is NVIDIA → AMD → Intel.

---

## Verifying Downloads

All release artifacts are GPG-signed and include SHA256 checksums.

```bash
# Import the signing key
gpg --import heatsync-signing-key.asc

# Verify a binary
gpg --verify HeatSync.AppImage.asc HeatSync.AppImage

# Verify checksums
sha256sum -c SHA256SUMS
```

---

## License

[MIT](LICENSE)
