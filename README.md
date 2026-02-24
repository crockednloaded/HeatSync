# HeatSync

**Real-time system monitor for Linux & Windows**

A dark-themed, frameless desktop widget inspired by NZXT CAM — built with PyQt6. Displays CPU and GPU temperature and usage via circular arc gauges with neon glow effects, sparkline history graphs, and a live status bar. Sits in your system tray and stays out of your way.

---

## Features

- **Circular arc gauges** — 300° sweep with thin neon glow for CPU temp, CPU usage, GPU temp, and GPU usage
- **Sparkline history graphs** — 90-point rolling history per metric
- **Color-coded alerts** — gauges shift to orange (warn) at 70–80% and red (danger) at 88–95%
- **Status bar** — RAM, VRAM, CPU frequency, thread count, and disk usage (used/total GB + %)
- **12-hour clock** in the title bar
- **Frameless window** — draggable from title bar, resizable from bottom-right grip
- **Dock-to-top** — snaps the window to the top edge of the monitor as a full-width bar; double-click the title bar or the dock button to toggle; drag while docked to undock and reposition
- **System tray only** — no taskbar icon; left-click the tray icon to show/hide; close button hides to tray
- **Auto-detects NVIDIA, AMD, and Intel GPUs** — NVIDIA via pynvml, AMD and Intel via sysfs (no extra drivers needed)
- **Intel CPU temperature** — via `coretemp` kernel driver, works out of the box on all Intel platforms
- **Dark aesthetic** — `#090b10` background, JetBrains Mono Nerd Font, neon cyan / green / purple / amber

---

## Screenshots

![HeatSync docked to top of monitor](assets/screenshot.png)

---

## Requirements

- Python 3.10+
- [PyQt6](https://pypi.org/project/PyQt6/)
- [psutil](https://pypi.org/project/psutil/)
- [nvidia-ml-py](https://pypi.org/project/nvidia-ml-py/) _(optional — required for NVIDIA GPU monitoring)_
- `qdbus6` _(Linux Wayland only — usually pre-installed with KDE Plasma)_

---

## Installation

### Linux

**Option 1 — AppImage (no Python required):**

Download the latest **HeatSync.AppImage** from the [Releases](https://github.com/crockednloaded/HeatSync/releases) page, then:

```bash
chmod +x HeatSync.AppImage
./HeatSync.AppImage
```

**Option 2 — Run from source:**

```bash
git clone https://github.com/crockednloaded/HeatSync.git
cd HeatSync
bash install.sh
```

`install.sh` creates a `.venv`, installs all dependencies, downloads the latest AppImage, and sets up autostart.

Tested on CachyOS / Arch Linux with KDE Plasma on both Wayland and X11.

### Windows

Download the pre-built **HeatSync.exe** from the [Releases](https://github.com/crockednloaded/HeatSync/releases) page — no Python required, just run it.

Or run from source:

```bat
git clone https://github.com/crockednloaded/HeatSync.git
cd HeatSync
install.bat
```

Tested on Windows 10 and Windows 11.

---

## Running

**Linux (AppImage)**

```bash
./HeatSync.AppImage
```

**Linux (from source)**

```bash
bash run.sh
# or
.venv/bin/python HeatSync.py
```

**Windows**

```bat
run.bat
rem or
.venv\Scripts\python.exe HeatSync.py
```

---

## Notes

### GPU Monitoring

**NVIDIA** GPUs are monitored via `pynvml` (nvidia-ml-py).

**AMD** GPUs are monitored via the `amdgpu` kernel driver's sysfs interface — usage, VRAM, and temperature are all supported. No extra software or drivers required.

**Intel Arc** discrete GPUs are monitored via the `xe`/`i915` kernel driver's sysfs interface — temperature, VRAM, and a frequency-based usage estimate are supported. Intel iGPUs (integrated graphics) are also detected and will show temperature and GTT memory usage.

Priority order when multiple GPUs are present: NVIDIA → AMD → Intel.

If no supported GPU is detected, GPU gauges will display as unavailable.

### CPU Temperature on Windows

On Windows, CPU temperature requires [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor) to be running in the background (free, open source). On Linux, temperature is read directly from kernel sensors — no additional software needed.

### Dock Button Behavior

- **Linux Wayland (KDE Plasma):** uses KWin scripting via `qdbus6`
- **Linux X11 / Windows:** uses Qt geometry directly

---

## Contributing

Contributions are welcome. Feel free to open an issue or submit a pull request for bug fixes, new features, or platform improvements.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes
4. Open a pull request

---

## License

This project is licensed under the [MIT License](LICENSE).
