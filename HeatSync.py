#!/usr/bin/env python3
"""
HeatSync — NZXT CAM-style system monitor
Supports Linux (X11 + Wayland/KWin) and Windows.
https://github.com/crockednloaded/HeatSync
"""

import sys
import os
import glob
import math
import socket
import warnings
import subprocess
import shutil
import tempfile
import time
import platform
from datetime import datetime

# ── Venv auto-reexec ─────────────────────────────────────────────────────────
# Prefer a local .venv in the script directory; fall back to ~/.sysmon_venv.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if sys.platform == "win32":
    _VENV_PY = os.path.join(_SCRIPT_DIR, ".venv", "Scripts", "python.exe")
else:
    _VENV_PY = os.path.join(_SCRIPT_DIR, ".venv", "bin", "python")
    _VENV_PY_LEGACY = os.path.expanduser("~/.sysmon_venv/bin/python")
    if not os.path.exists(_VENV_PY) and os.path.exists(_VENV_PY_LEGACY):
        _VENV_PY = _VENV_PY_LEGACY

if os.path.exists(_VENV_PY) and os.path.abspath(sys.executable) != os.path.abspath(_VENV_PY):
    os.execv(_VENV_PY, [_VENV_PY] + sys.argv)

from collections import deque

import psutil
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy,
    QGraphicsDropShadowEffect, QSystemTrayIcon, QMenu,
)
from PyQt6.QtCore  import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui   import (
    QPainter, QColor, QPen, QFont, QPainterPath,
    QLinearGradient, QBrush, QPalette,
    QIcon, QPixmap,
)

# ── Version ───────────────────────────────────────────────────────────────────
def _get_version() -> str:
    """Read version from git tags at runtime; fall back to the hardcoded value
    (which CI replaces before packaging the standalone EXE / AppImage)."""
    try:
        r = subprocess.run(
            ["git", "describe", "--tags", "--abbrev=0"],
            capture_output=True, text=True, timeout=3, cwd=_SCRIPT_DIR,
        )
        if r.returncode == 0:
            tag = r.stdout.strip()
            if tag:
                return tag
    except Exception:
        pass
    return "v1.0.22"  # fallback — replaced by CI before build

VERSION = _get_version()

# ── Platform flags ────────────────────────────────────────────────────────────
IS_WINDOWS = sys.platform == "win32"
IS_WAYLAND = (sys.platform == "linux" and
              bool(os.environ.get("WAYLAND_DISPLAY") or
                   os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"))

# ── GPU init (NVIDIA via pynvml, AMD via sysfs, Intel via sysfs) ─────────────
GPU_HANDLE  = None    # pynvml handle — set if NVIDIA found
GPU_NAME    = "GPU Unavailable"
_AMD_DEV    = None    # /sys/class/drm/cardX/device — set if AMD found
_AMD_HWMON  = None    # /sys/class/drm/cardX/device/hwmon/hwmonY
_INTEL_DEV  = None    # /sys/class/drm/cardX/device — set if Intel found
_INTEL_HWMON = None   # /sys/class/drm/cardX/device/hwmon/hwmonY

# Try NVIDIA first
try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import pynvml
    pynvml.nvmlInit()
    GPU_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
    _n = pynvml.nvmlDeviceGetName(GPU_HANDLE)
    GPU_NAME = _n.decode() if isinstance(_n, bytes) else _n
except Exception:
    pass

# Try AMD/Intel if no NVIDIA found (Linux only — uses kernel driver sysfs)
if not GPU_HANDLE and sys.platform == "linux":
    def _gpu_name_from_sysfs(card: str, fallback: str) -> str:
        try:
            with open(os.path.join(card, "product_name")) as f:
                n = f.read().strip()
                if n: return n
        except Exception:
            pass
        try:
            with open(os.path.join(card, "uevent")) as f:
                slot = next((l.split("=",1)[1].strip() for l in f
                             if l.startswith("PCI_SLOT_NAME=")), None)
            if slot:
                r = subprocess.run(["lspci", "-s", slot],
                                   capture_output=True, text=True, timeout=3)
                if r.returncode == 0:
                    parts = r.stdout.strip().split(":", 2)
                    if len(parts) >= 3:
                        return parts[2].strip()
        except Exception:
            pass
        return fallback

    # Collect all DRM cards with their vendor IDs
    _cards: list[tuple[str, str]] = []
    for _card in sorted(glob.glob("/sys/class/drm/card*/device")):
        try:
            with open(os.path.join(_card, "vendor")) as _f:
                _cards.append((_f.read().strip(), _card))
        except Exception:
            pass

    # Prefer AMD discrete (0x1002) over Intel iGPU (0x8086)
    for _wanted in ("0x1002", "0x8086"):
        for _vendor, _card in _cards:
            if _vendor != _wanted:
                continue
            _hw = glob.glob(os.path.join(_card, "hwmon", "hwmon*"))
            _hwmon = _hw[0] if _hw else None
            if _wanted == "0x1002":
                _AMD_DEV, _AMD_HWMON = _card, _hwmon
                GPU_NAME = _gpu_name_from_sysfs(_card, "AMD GPU")
                print(f"[INFO] AMD GPU: {GPU_NAME}")
            else:
                _INTEL_DEV, _INTEL_HWMON = _card, _hwmon
                GPU_NAME = _gpu_name_from_sysfs(_card, "Intel GPU")
                print(f"[INFO] Intel GPU: {GPU_NAME}")
            break
        if _AMD_DEV or _INTEL_DEV:
            break
    else:
        print("[WARN] No supported GPU found (NVIDIA, AMD, or Intel)")

# ── Palette ──────────────────────────────────────────────────────────────────
BG       = "#090b10"
CARD_BG  = "#0e1018"
CARD_BD  = "#1a1d2b"
TXT_HI   = "#e5e8f0"
TXT_MID  = "#848ba0"
TXT_LO   = "#404560"

CYAN   = "#00ccdd"
GREEN  = "#00e676"
PURPLE = "#9d6fff"
AMBER  = "#ffa040"
C_WARN = "#ff9800"
C_DANG = "#f44336"

# ── Font helper ──────────────────────────────────────────────────────────────
_FONT_FAMILIES = ["JetBrainsMono NF", "JetBrainsMono Nerd Font", "JetBrains Mono",
                  "Consolas", "Hack", "Fira Mono", "Fira Sans", "Sans Serif"]

def _font(px: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(_FONT_FAMILIES)
    f.setPixelSize(max(8, int(px)))
    if bold:
        f.setWeight(QFont.Weight.Bold)
    return f

def _make_tray_icon() -> QIcon:
    icon_path = os.path.join(_SCRIPT_DIR, "assets", "icon.png")
    if os.path.exists(icon_path):
        return QIcon(icon_path)
    # Fallback: draw a simple arc icon
    px = QPixmap(32, 32)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor("#1c1f2e"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
    p.drawArc(QRectF(4, 4, 24, 24), 240 * 16, -300 * 16)
    p.setPen(QPen(QColor(CYAN), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    p.drawArc(QRectF(4, 4, 24, 24), 240 * 16, -180 * 16)
    p.end()
    return QIcon(px)

def _get_cpu_name() -> str:
    """Detect CPU model name across platforms."""
    if IS_WINDOWS:
        return platform.processor() or "CPU"
    try:
        with open("/proc/cpuinfo") as fh:
            for line in fh:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except Exception:
        pass
    return platform.processor() or "CPU"

# ── Sensors ──────────────────────────────────────────────────────────────────
psutil.cpu_percent()   # prime — first call is always 0.0

def s_cpu_usage() -> float:
    return psutil.cpu_percent()

def s_cpu_temp() -> float:
    if IS_WINDOWS:
        # Requires LibreHardwareMonitor to be running
        try:
            import wmi  # type: ignore
            w = wmi.WMI(namespace="root\\LibreHardwareMonitor")
            for s in w.Sensor():
                if s.SensorType == "Temperature" and "CPU" in s.Name and "Package" in s.Name:
                    return float(s.Value)
        except Exception:
            pass
        return 0.0
    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            return 0.0
        # Known driver keys with preferred label names (AMD + Intel + ARM)
        _PREF: list[tuple[str, tuple[str, ...]]] = [
            ("k10temp",    ("Tctl", "Tdie", "Tccd1")),
            ("zenpower",   ("Tctl", "Tdie")),
            ("coretemp",   ("Package id 0", "Physical id 0")),
            ("cpu_thermal", ()),   # Raspberry Pi / ARM SoCs
            ("acpitz",     ()),    # ACPI generic thermal zone
        ]
        for key, good_labels in _PREF:
            if key not in temps:
                continue
            entries = temps[key]
            if good_labels:
                hit = next((e.current for e in entries if e.label in good_labels), None)
                if hit is not None:
                    return hit
            if entries:
                return entries[0].current
        # Generic fallback: scan all sensor groups for a plausible CPU temp
        def _plausible(v: float) -> bool: return 20.0 <= v <= 120.0
        for prefer_cpu in (True, False):
            for key, entries in temps.items():
                if prefer_cpu and "cpu" not in key.lower():
                    continue
                for e in entries:
                    if _plausible(e.current):
                        return e.current
    except Exception:
        pass
    return 0.0

def s_gpu_usage() -> float:
    if GPU_HANDLE:
        try:
            return float(pynvml.nvmlDeviceGetUtilizationRates(GPU_HANDLE).gpu)
        except Exception:
            return 0.0
    if _AMD_DEV:
        try:
            with open(os.path.join(_AMD_DEV, "gpu_busy_percent")) as f:
                return float(f.read().strip())
        except Exception:
            return 0.0
    if _INTEL_DEV:
        # i915/xe don't expose a usage % via sysfs; use freq0_input/freq0_max
        # as a rough activity proxy (current freq / max freq).
        if _INTEL_HWMON:
            try:
                cur = float(open(os.path.join(_INTEL_HWMON, "freq0_input")).read().strip())
                mx  = float(open(os.path.join(_INTEL_HWMON, "freq0_max")).read().strip())
                if mx > 0:
                    return min(100.0, cur / mx * 100.0)
            except Exception:
                pass
        return 0.0
    return 0.0

def s_gpu_temp() -> float:
    if GPU_HANDLE:
        try:
            return float(pynvml.nvmlDeviceGetTemperature(
                GPU_HANDLE, pynvml.NVML_TEMPERATURE_GPU))
        except Exception:
            return 0.0
    if _AMD_DEV:
        # Prefer hwmon temp1_input (millidegrees → °C)
        if _AMD_HWMON:
            try:
                with open(os.path.join(_AMD_HWMON, "temp1_input")) as f:
                    return float(f.read().strip()) / 1000.0
            except Exception:
                pass
        # Fallback: psutil amdgpu sensor
        try:
            temps = psutil.sensors_temperatures()
            if "amdgpu" in temps and temps["amdgpu"]:
                return temps["amdgpu"][0].current
        except Exception:
            pass
    if _INTEL_DEV:
        # Intel GPU temperature via hwmon or psutil
        if _INTEL_HWMON:
            # Try temp1_input (i915 and xe drivers use hwmon)
            try:
                with open(os.path.join(_INTEL_HWMON, "temp1_input")) as f:
                    return float(f.read().strip()) / 1000.0
            except Exception:
                pass
        # Fallback: psutil i915 or xe sensor
        try:
            temps = psutil.sensors_temperatures()
            for key in ["i915", "xe", "intel_gpu"]:
                if key in temps and temps[key]:
                    return temps[key][0].current
        except Exception:
            pass
    return 0.0

def s_gpu_vram():
    if GPU_HANDLE:
        try:
            m = pynvml.nvmlDeviceGetMemoryInfo(GPU_HANDLE)
            pct = m.used / m.total * 100 if m.total else 0
            return m.used >> 20, m.total >> 20, pct
        except Exception:
            return 0, 0, 0
    if _AMD_DEV:
        try:
            with open(os.path.join(_AMD_DEV, "mem_info_vram_used")) as f:
                used = int(f.read().strip())
            with open(os.path.join(_AMD_DEV, "mem_info_vram_total")) as f:
                total = int(f.read().strip())
            pct = used / total * 100 if total else 0
            return used >> 20, total >> 20, pct
        except Exception:
            pass
    if _INTEL_DEV:
        # Try dedicated VRAM first (Intel Arc discrete), then GTT (iGPU approximation)
        for uf, tf in (("mem_info_vram_used", "mem_info_vram_total"),
                       ("mem_info_gtt_used",  "mem_info_gtt_total")):
            up = os.path.join(_INTEL_DEV, uf)
            tp = os.path.join(_INTEL_DEV, tf)
            if os.path.exists(up) and os.path.exists(tp):
                try:
                    used  = int(open(up).read().strip())
                    total = int(open(tp).read().strip())
                    pct   = used / total * 100 if total else 0
                    return used >> 20, total >> 20, pct
                except Exception:
                    pass
    return 0, 0, 0

def s_ram():
    v = psutil.virtual_memory()
    return v.used / 1e9, v.total / 1e9, v.percent

def s_cpu_freq() -> float:
    f = psutil.cpu_freq()
    return f.current / 1000.0 if f else 0.0

def s_disk():
    """Returns (used_GB, total_GB, percent) for the root / boot drive."""
    path = "C:\\" if IS_WINDOWS else "/"
    d = psutil.disk_usage(path)
    return d.used / 1e9, d.total / 1e9, d.percent

# ── Arc Gauge ────────────────────────────────────────────────────────────────
class ArcGauge(QWidget):
    _DEG_START = 240
    _DEG_SPAN  = -300
    _HALOS = ((14, 10), (9, 22), (6, 40))

    def __init__(self, label, unit, lo=0, hi=100, color=CYAN, warn=75, danger=90):
        super().__init__()
        self._label   = label
        self._unit    = unit
        self._lo, self._hi = lo, hi
        self._col     = QColor(color)
        self._c_warn  = QColor(C_WARN)
        self._c_dang  = QColor(C_DANG)
        self._warn    = warn
        self._danger  = danger
        self._target  = 0.0
        self._cur     = 0.0
        self.setMinimumSize(190, 210)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        t = QTimer(self); t.timeout.connect(self._tick); t.start(15)

    def set_value(self, v):
        self._target = max(self._lo, min(self._hi, v))

    def _tick(self):
        delta = self._target - self._cur
        if abs(delta) > 0.02:
            self._cur += delta * 0.13
            self.update()
        elif self._cur != self._target:
            self._cur = self._target
            self.update()

    def _active_col(self):
        pct = (self._cur - self._lo) / max(self._hi - self._lo, 1e-9) * 100
        if pct >= self._danger: return self._c_dang
        if pct >= self._warn:   return self._c_warn
        return self._col

    def paintEvent(self, _e):
        W, H   = self.width(), self.height()
        margin = 22
        side   = min(W, H) - margin * 2
        rx, ry = (W - side) / 2, (H - side) / 2 - 8
        rect   = QRectF(rx, ry, side, side)
        r2     = side / 2
        cx, cy = rx + r2, ry + r2

        a0    = self._DEG_START * 16
        a_end = self._DEG_SPAN  * 16
        pct   = max(0.0, min(1.0, (self._cur - self._lo) / max(self._hi - self._lo, 1e-9)))
        a_val = int(a_end * pct)
        col   = self._active_col()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(Qt.BrushStyle.NoBrush)

        trk = QPen(QColor("#1c1f2e"), 3); trk.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(trk); p.drawArc(rect, a0, a_end)

        if pct > 5e-3:
            for pw, al in self._HALOS:
                c = QColor(col); c.setAlpha(al)
                pk = QPen(c, pw); pk.setCapStyle(Qt.PenCapStyle.FlatCap)
                p.setPen(pk); p.drawArc(rect, a0, a_val)
            pk = QPen(col, 3); pk.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pk); p.drawArc(rect, a0, a_val)
            tip_ang = math.radians(self._DEG_START + self._DEG_SPAN * pct)
            tip_x   = cx + r2 * math.cos(tip_ang)
            tip_y   = cy - r2 * math.sin(tip_ang)
            for dr, da in ((8, 15), (5, 50), (2.5, 230)):
                c = QColor(col); c.setAlpha(da)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
                p.drawEllipse(QPointF(tip_x, tip_y), dr, dr)
            p.setBrush(Qt.BrushStyle.NoBrush)

        val_str = f"{self._cur:.0f}{self._unit}"
        blend   = 0.25
        col_rgb = (col.red(), col.green(), col.blue())
        val_col = QColor(
            min(255, int(229 * (1 - blend) + col_rgb[0] * blend)),
            min(255, int(232 * (1 - blend) + col_rgb[1] * blend)),
            min(255, int(240 * (1 - blend) + col_rgb[2] * blend)),
        )
        fs = max(10, int(side * 0.22 * (4 / max(len(val_str), 4))))
        p.setFont(_font(fs, bold=True)); p.setPen(val_col)
        p.drawText(QRectF(0, cy - side * 0.17, W, side * 0.34),
                   Qt.AlignmentFlag.AlignCenter, val_str)

        p.setFont(_font(max(8, int(side * 0.085)))); p.setPen(QColor(TXT_MID))
        p.drawText(QRectF(0, cy + side * 0.20, W, side * 0.18),
                   Qt.AlignmentFlag.AlignCenter, self._label)
        p.end()


# ── Sparkline ────────────────────────────────────────────────────────────────
class Sparkline(QWidget):
    def __init__(self, color=CYAN, max_pts=90, unit=""):
        super().__init__()
        self._col  = QColor(color)
        self._hist: deque = deque(maxlen=max_pts)
        self._unit = unit
        self._hover_x = -1.0
        self.setFixedHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)

    def push(self, v):
        self._hist.append(v); self.update()

    def mouseMoveEvent(self, e):
        if len(self._hist) < 2:
            return
        self._hover_x = e.position().x()
        self.update()

    def leaveEvent(self, e):
        self._hover_x = -1.0
        self.update()
        super().leaveEvent(e)

    def paintEvent(self, _e):
        if len(self._hist) < 2: return
        W, H = self.width(), self.height()
        px, py = 3, 6
        vals = list(self._hist)
        hi   = max(max(vals), 1.0)
        n    = len(vals)
        fx   = lambda i: px + i / (n - 1) * (W - 2 * px)
        fy   = lambda v: H - py - v / hi * (H - 2 * py)
        pts  = [QPointF(fx(i), fy(v)) for i, v in enumerate(vals)]

        line = QPainterPath(); line.moveTo(pts[0])
        for i in range(1, n):
            mid = (pts[i-1].x() + pts[i].x()) / 2
            line.cubicTo(QPointF(mid, pts[i-1].y()), QPointF(mid, pts[i].y()), pts[i])

        area = QPainterPath(line)
        area.lineTo(QPointF(pts[-1].x(), H))
        area.lineTo(QPointF(pts[0].x(),  H))
        area.closeSubpath()

        grad = QLinearGradient(0, 0, 0, H)
        top  = QColor(self._col); top.setAlpha(55)
        bot  = QColor(self._col); bot.setAlpha(0)
        grad.setColorAt(0, top); grad.setColorAt(1, bot)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillPath(area, QBrush(grad))
        p.setPen(QPen(self._col, 1.7, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawPath(line)
        tip = pts[-1]
        for dr, da in ((7, 18), (4.5, 60), (2.5, 240)):
            c = QColor(self._col); c.setAlpha(da)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
            p.drawEllipse(tip, dr, dr)

        # hover indicator — pixel-accurate via interpolation
        if self._hover_x >= 0:
            mx = max(pts[0].x(), min(pts[-1].x(), self._hover_x))
            # find the segment containing mx and interpolate
            hp, hval = pts[-1], vals[-1]
            for i in range(len(pts) - 1):
                x0, x1 = pts[i].x(), pts[i + 1].x()
                if x0 <= mx <= x1:
                    t    = (mx - x0) / (x1 - x0) if x1 > x0 else 0.0
                    hy   = pts[i].y()   + t * (pts[i + 1].y()   - pts[i].y())
                    hval = vals[i]      + t * (vals[i + 1]       - vals[i])
                    hp   = QPointF(mx, hy)
                    break

            vc = QColor(self._col); vc.setAlpha(40)
            p.setPen(QPen(vc, 1, Qt.PenStyle.SolidLine))
            p.drawLine(QPointF(hp.x(), py), QPointF(hp.x(), H))
            for dr, da in ((6, 25), (3.5, 80), (2, 220)):
                c = QColor(self._col); c.setAlpha(da)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
                p.drawEllipse(hp, dr, dr)

            label = f"{hval:.1f}{self._unit}"
            p.setFont(_font(10, bold=True))
            fm  = p.fontMetrics()
            pad = 4
            bw  = fm.horizontalAdvance(label) + pad * 2
            bh  = fm.height() + pad * 2
            bx  = min(max(hp.x() - bw / 2, 0), W - bw)
            by  = 2
            bg  = QColor(CARD_BG); bg.setAlpha(210)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(bg))
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 4, 4)
            bc = QColor(self._col); bc.setAlpha(160)
            p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(bx, by, bw, bh), 4, 4)
            p.setPen(QColor(TXT_HI))
            p.drawText(QRectF(bx, by, bw, bh), Qt.AlignmentFlag.AlignCenter, label)

        p.end()


# ── Monitor Card ─────────────────────────────────────────────────────────────
class MonitorCard(QFrame):
    _R = 18.0

    def __init__(self, label, unit, lo=0, hi=100, color=CYAN, warn=75, danger=90):
        super().__init__()
        self._accent = QColor(color)
        self.gauge   = ArcGauge(label, unit, lo, hi, color, warn, danger)
        self.spark   = Sparkline(color, unit=unit)

        sep = QFrame(); sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {CARD_BD}; border: none; border-radius: 0;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 14, 10, 10); lay.setSpacing(8)
        lay.addWidget(self.gauge, 1); lay.addWidget(sep); lay.addWidget(self.spark)

        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(28); sh.setColor(QColor(0, 0, 0, 160)); sh.setOffset(0, 5)
        self.setGraphicsEffect(sh)

    def push(self, v):
        self.gauge.set_value(v); self.spark.push(v)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1); R = self._R
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(QColor(CARD_BG)))
        p.drawRoundedRect(r, R, R)
        grad = QLinearGradient(0, 0, 0, 72)
        c0 = QColor(self._accent); c0.setAlpha(38)
        c1 = QColor(self._accent); c1.setAlpha(0)
        grad.setColorAt(0, c0); grad.setColorAt(1, c1)
        p.setBrush(QBrush(grad)); p.drawRoundedRect(r, R, R)
        bc = QColor(self._accent); bc.setAlpha(55)
        p.setPen(QPen(bc, 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, R, R); p.end()


# ── Status Bar ───────────────────────────────────────────────────────────────
class StatusBar(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(34)
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 6, 0); lay.setSpacing(32)
        self._lbs: dict[str, QLabel] = {}
        for key in ("RAM", "VRAM", "CPU Freq", "Threads", "Disk"):
            lb = QLabel(f"{key}: –")
            lb.setFont(_font(12))
            lb.setStyleSheet(f"color: {TXT_MID}; background: transparent;")
            self._lbs[key] = lb; lay.addWidget(lb)
        lay.addStretch()

    def refresh(self):
        used_r, tot_r, pct_r = s_ram()
        self._lbs["RAM"].setText(f"RAM  {used_r:.1f} / {tot_r:.0f} GB  ({pct_r:.0f}%)")

        used_v, tot_v, pct_v = s_gpu_vram()
        self._lbs["VRAM"].setText(
            f"VRAM  {used_v:,} / {tot_v:,} MB  ({pct_v:.0f}%)" if tot_v else "VRAM  N/A"
        )

        self._lbs["CPU Freq"].setText(f"CPU Freq  {s_cpu_freq():.2f} GHz")
        self._lbs["Threads"].setText(f"Threads  {psutil.cpu_count(logical=True)}")

        used_d, tot_d, pct_d = s_disk()
        self._lbs["Disk"].setText(f"Disk  {used_d:.0f} / {tot_d:.0f} GB  ({pct_d:.0f}%)")


# ── Window control button ─────────────────────────────────────────────────────
class _WinBtn(QWidget):
    def __init__(self, symbol, color, callback):
        super().__init__()
        self._symbol = symbol; self._color = QColor(color)
        self._dim = QColor(color).darker(140); self._cb = callback
        self._hovered = False; self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def enterEvent(self, _e): self._hovered = True;  self.update()
    def leaveEvent(self, _e): self._hovered = False; self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: self._cb()

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color if self._hovered else self._dim)
        p.drawEllipse(0, 0, 16, 16)
        if self._hovered:
            p.setFont(_font(9, bold=True)); p.setPen(QColor(0, 0, 0, 210))
            p.drawText(QRectF(0, 0, 16, 16), Qt.AlignmentFlag.AlignCenter, self._symbol)
        p.end()


# ── Dock-to-top button ───────────────────────────────────────────────────────
class _DockBtn(QWidget):
    def __init__(self, callback):
        super().__init__()
        self._cb = callback; self._active = False; self._hovered = False
        self.setFixedSize(26, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_active(self, v): self._active = v; self.update()
    def enterEvent(self, _e): self._hovered = True;  self.update()
    def leaveEvent(self, _e): self._hovered = False; self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton: self._cb()

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H  = self.width(), self.height()
        rim_c = QColor(CYAN) if (self._active or self._hovered) else QColor(TXT_LO)
        p.setPen(QPen(rim_c, 1.2)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 2.5, 2.5)
        bar_c = QColor(CYAN if self._active else rim_c.name())
        bar_c.setAlpha(220 if self._active else (160 if self._hovered else 90))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(bar_c))
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, 5), 2.5, 2.5); p.end()


# ── Resize grip ───────────────────────────────────────────────────────────────
class ResizeGrip(QWidget):
    def __init__(self, parent_win):
        super().__init__(parent_win)
        self._win = parent_win; self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            h = self._win.windowHandle()
            if h: h.startSystemResize(Qt.Edge.RightEdge | Qt.Edge.BottomEdge)

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(TXT_LO), 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for i in range(3):
            o = 5 + i * 5; p.drawLine(o, 20, 20, o)
        p.end()


# ── Title / Drag Bar ──────────────────────────────────────────────────────────
class TitleBar(QWidget):
    def __init__(self, parent_win):
        super().__init__(parent_win)
        self._win = parent_win
        self._last_press_ms = 0.0
        self._press_pos = None  # set when docked+pressed; cleared on release/drag/dblclick
        self.setFixedHeight(52)
        self.setStyleSheet("background: transparent;")
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 14, 0); lay.setSpacing(0)

        title = QLabel(f"◈  HEATSYNC")
        title.setFont(_font(17, bold=True))
        title.setStyleSheet(f"color: {CYAN}; letter-spacing: 3px; background: transparent;")

        ver_lbl = QLabel(VERSION)
        ver_lbl.setFont(_font(10))
        ver_lbl.setStyleSheet(f"color: {TXT_LO}; background: transparent;")
        ver_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # CPU + GPU names stacked vertically so they never get clipped
        cpu_name = _get_cpu_name()
        hw_box = QWidget()
        hw_box.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        hw_box.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        hw_v = QVBoxLayout(hw_box)
        hw_v.setContentsMargins(10, 0, 0, 0); hw_v.setSpacing(1)
        for hw_text in (cpu_name, GPU_NAME):
            lbl = QLabel(hw_text)
            lbl.setFont(_font(11))
            lbl.setStyleSheet(f"color: {TXT_LO}; background: transparent;")
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            hw_v.addWidget(lbl)

        self._clk = QLabel()
        self._clk.setFont(_font(14))
        self._clk.setStyleSheet(f"color: {TXT_MID}; background: transparent;")
        self._tick()
        t = QTimer(self); t.timeout.connect(self._tick); t.start(1000)

        btn_min       = _WinBtn("−", "#ffbd2e", parent_win.showMinimized)
        btn_cls       = _WinBtn("✕", "#ff5f57", parent_win.close)
        self.dock_btn = _DockBtn(parent_win.toggle_dock)
        for btn in (btn_min, btn_cls, self.dock_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        for lbl in (title, self._clk):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        lay.addWidget(title); lay.addSpacing(6); lay.addWidget(ver_lbl); lay.addWidget(hw_box)
        lay.addStretch()
        lay.addWidget(self._clk); lay.addSpacing(18)
        lay.addWidget(self.dock_btn); lay.addSpacing(10)
        lay.addWidget(btn_min); lay.addSpacing(8); lay.addWidget(btn_cls)

    def _tick(self):
        self._clk.setText(datetime.now().strftime("%I:%M:%S %p   %a %d %b %Y"))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            now = time.monotonic() * 1000
            dt, self._last_press_ms = now - self._last_press_ms, now
            if dt > QApplication.doubleClickInterval():
                if self._win._docked:
                    # Docked: hold off on startSystemMove so we can detect a
                    # drag in mouseMoveEvent without the compositor stealing it
                    self._press_pos = e.position()
                else:
                    h = self._win.windowHandle()
                    if h: h.startSystemMove()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if (self._press_pos is not None
                and self._win._docked
                and e.buttons() & Qt.MouseButton.LeftButton):
            delta = e.position() - self._press_pos
            if abs(delta.x()) + abs(delta.y()) > QApplication.startDragDistance():
                self._press_pos = None
                self._win.toggle_dock(via_drag=True)
                h = self._win.windowHandle()
                if h: h.startSystemMove()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos = None
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._press_pos = None
            self._win.toggle_dock()
        super().mouseDoubleClickEvent(e)


# ── Rounded window background ────────────────────────────────────────────────
class _Background(QWidget):
    _R = 16.0

    def set_squared(self, squared):
        self._R = 0.0 if squared else 16.0; self.update()

    def paintEvent(self, _e):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(QColor(BG)))
        p.drawRoundedRect(r, self._R, self._R)
        p.setPen(QPen(QColor("#1e2238"), 1)); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, self._R, self._R); p.end()


# ── Main Window ──────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HeatSync")

        # On Windows / X11: Tool flag hides from taskbar natively.
        # On Wayland: Tool breaks KWin windowList(); use FramelessHint only
        #             and ask KWin to set skipTaskbar via D-Bus instead.
        if IS_WAYLAND:
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        else:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
            )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(880, 480)
        self.resize(1080, 540)

        self._docked        = False
        self._pre_dock_geom = None

        cw = _Background()
        self.setCentralWidget(cw)

        root = QVBoxLayout(cw)
        root.setContentsMargins(14, 8, 14, 12); root.setSpacing(8)

        self._title_bar = TitleBar(self)
        root.addWidget(self._title_bar)

        div = QFrame(); div.setFixedHeight(1)
        div.setStyleSheet(f"background: {CARD_BD}; border: none;")
        root.addWidget(div)

        row = QHBoxLayout(); row.setSpacing(12)
        self._cu = MonitorCard("CPU USAGE", "%",   0, 100, CYAN,   70, 90)
        self._ct = MonitorCard("CPU TEMP",  "°C",  0, 105, GREEN,  80, 95)
        self._gu = MonitorCard("GPU USAGE", "%",   0, 100, PURPLE, 70, 90)
        self._gt = MonitorCard("GPU TEMP",  "°C",  0,  95, AMBER,  75, 88)
        for card in (self._cu, self._ct, self._gu, self._gt):
            row.addWidget(card)
        root.addLayout(row, 1)

        div2 = QFrame(); div2.setFixedHeight(1)
        div2.setStyleSheet(f"background: {CARD_BD}; border: none;")
        root.addWidget(div2)

        bot = QHBoxLayout(); bot.setContentsMargins(0, 0, 0, 0); bot.setSpacing(0)
        self._sb = StatusBar()
        bot.addWidget(self._sb, 1); bot.addWidget(ResizeGrip(self))
        root.addLayout(bot)

        t = QTimer(self); t.timeout.connect(self._refresh); t.start(1000)
        self._refresh()

        # System tray (optional — not all desktops/WMs provide one)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = QSystemTrayIcon(self)
            self._tray.setIcon(_make_tray_icon())
            self._tray.setToolTip(f"HeatSync {VERSION}")
            menu = QMenu()
            menu.addAction("Show / Hide").triggered.connect(self._toggle_visibility)
            menu.addAction("Quit").triggered.connect(QApplication.instance().quit)
            self._tray.setContextMenu(menu)
            self._tray.activated.connect(self._tray_activated)
            self._tray.show()
        else:
            self._tray = None
            print("[INFO] No system tray available — close button will quit.")

        if IS_WAYLAND:
            QTimer.singleShot(600, self._kwin_skip_taskbar)

    def closeEvent(self, e):
        if self._tray and self._tray.isVisible():
            self.hide(); e.ignore()
        else:
            e.accept()

    def _toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show(); self.raise_(); self.activateWindow()
            if IS_WAYLAND:
                QTimer.singleShot(400, self._kwin_skip_taskbar)

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_visibility()

    # ── KWin scripting (Linux Wayland only) ───────────────────────────────────
    def _kwin_run(self, js: str, tag: str = "hs") -> bool:
        """Load and run a one-shot KWin JS script. Returns True on success.

        Uses loadScript → start() → unloadScript to avoid per-script D-Bus
        path timing issues. start() only executes scripts not yet run.
        """
        if not IS_WAYLAND:
            return False
        qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
        if not qdbus:
            return False
        plugin = f"{tag}_{os.getpid()}_{int(time.monotonic() * 1000) & 0xFFFFFF}"
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".js", delete=False
            ) as fh:
                fh.write(js); tmp = fh.name
            subprocess.run(
                [qdbus, "org.kde.KWin", "/Scripting",
                 "org.kde.kwin.Scripting.loadScript", tmp, plugin],
                capture_output=True, timeout=3,
            )
            subprocess.run(
                [qdbus, "org.kde.KWin", "/Scripting",
                 "org.kde.kwin.Scripting.start"],
                timeout=3,
            )
            subprocess.run(
                [qdbus, "org.kde.KWin", "/Scripting",
                 "org.kde.kwin.Scripting.unloadScript", plugin],
                capture_output=True, timeout=3,
            )
            os.unlink(tmp)
            return True
        except Exception as e:
            print(f"[WARN] KWin script failed ({tag}): {e}")
            return False

    def _kwin_skip_taskbar(self):
        self._kwin_run(
            "var wins = workspace.windowList();"
            "for (var i = 0; i < wins.length; i++) {"
            "  if (wins[i].resourceClass === 'heatsync') {"
            "    wins[i].skipTaskbar = true;"
            "    wins[i].skipPager = true; break;"
            "  }"
            "}",
            tag="hs_skiptb",
        )

    def _kwin_move(self, x: int, y: int) -> bool:
        """Reposition HeatSync via KWin scripting (Wayland only)."""
        return self._kwin_run(
            f"var wins = workspace.windowList();"
            f"for (var i = 0; i < wins.length; i++) {{"
            f"  if (wins[i].resourceClass === 'heatsync') {{"
            f"    var g = wins[i].frameGeometry;"
            f"    wins[i].frameGeometry = {{x:{x}, y:{y}, width:g.width, height:g.height}};"
            f"    break;"
            f"  }}"
            f"}}",
            tag="hs_move",
        )

    # ── Dock toggle ───────────────────────────────────────────────────────────
    def toggle_dock(self, via_drag: bool = False):
        cw = self.centralWidget()
        if not self._docked:
            self._pre_dock_geom = self.geometry()
            ag = self.screen().availableGeometry()
            tx, ty = ag.x(), ag.y()
            self.resize(ag.width(), self.height())
            if IS_WAYLAND:
                QTimer.singleShot(250, lambda: self._kwin_move(tx, ty))
            else:
                self.move(tx, ty)
            self._docked = True
            if isinstance(cw, _Background): cw.set_squared(True)
        else:
            if self._pre_dock_geom is not None:
                self.resize(self._pre_dock_geom.width(), self._pre_dock_geom.height())
                if not via_drag:
                    px, py = self._pre_dock_geom.x(), self._pre_dock_geom.y()
                    if IS_WAYLAND:
                        QTimer.singleShot(250, lambda: self._kwin_move(px, py))
                    else:
                        self.move(px, py)
            self._docked = False
            if isinstance(cw, _Background): cw.set_squared(False)
        self._title_bar.dock_btn.set_active(self._docked)

    def _refresh(self):
        self._cu.push(s_cpu_usage())
        self._ct.push(s_cpu_temp())
        self._gu.push(s_gpu_usage())
        self._gt.push(s_gpu_temp())
        self._sb.refresh()


# ── Single-instance lock ──────────────────────────────────────────────────────
_LOCK_SOCK = None

def _acquire_instance_lock() -> bool:
    """Bind a socket that acts as a single-instance lock. Returns False if
    another instance is already running."""
    global _LOCK_SOCK
    try:
        if sys.platform == "linux":
            # Abstract Unix socket — kernel auto-releases it when the process exits
            _LOCK_SOCK = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            _LOCK_SOCK.bind("\0heatsync_instance_v1")
        else:
            _LOCK_SOCK = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            _LOCK_SOCK.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
            _LOCK_SOCK.bind(("127.0.0.1", 47321))
        return True
    except OSError:
        return False


# ── Entry point ──────────────────────────────────────────────────────────────
def main():
    if not _acquire_instance_lock():
        # Another instance is already running — exit silently
        sys.exit(0)

    app = QApplication(sys.argv)
    app.setApplicationName("HeatSync")
    if IS_WAYLAND:
        app.setDesktopFileName("heatsync")   # sets Wayland app_id → KWin resourceClass
    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window,          QColor(BG))
    pal.setColor(QPalette.ColorRole.WindowText,      QColor(TXT_HI))
    pal.setColor(QPalette.ColorRole.Base,            QColor(CARD_BG))
    pal.setColor(QPalette.ColorRole.AlternateBase,   QColor(CARD_BD))
    pal.setColor(QPalette.ColorRole.Text,            QColor(TXT_HI))
    pal.setColor(QPalette.ColorRole.Button,          QColor(CARD_BG))
    pal.setColor(QPalette.ColorRole.ButtonText,      QColor(TXT_HI))
    pal.setColor(QPalette.ColorRole.Highlight,       QColor(CYAN))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor(BG))
    app.setPalette(pal)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
