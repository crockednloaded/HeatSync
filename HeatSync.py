#!/usr/bin/env python3
"""
HeatSync — NZXT CAM-style system monitor
Supports Linux (X11 + Wayland/KWin) and Windows.
https://github.com/crockednloaded/HeatSync
"""

import sys
import os
import glob
import json
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
_SCRIPT_DIR    = os.path.dirname(os.path.abspath(__file__))
_SETTINGS_FILE = os.path.join(os.path.expanduser("~"), ".heatsync.json")
if sys.platform == "win32":
    _VENV_PY = os.path.join(_SCRIPT_DIR, ".venv", "Scripts", "python.exe")
else:
    _VENV_PY = os.path.join(_SCRIPT_DIR, ".venv", "bin", "python")
    _VENV_PY_LEGACY = os.path.expanduser("~/.sysmon_venv/bin/python")
    if not os.path.exists(_VENV_PY) and os.path.exists(_VENV_PY_LEGACY):
        _VENV_PY = _VENV_PY_LEGACY

if (not getattr(sys, "frozen", False)
        and os.path.exists(_VENV_PY)
        and os.path.abspath(sys.executable) != os.path.abspath(_VENV_PY)):
    os.execv(_VENV_PY, [_VENV_PY] + sys.argv)

from collections import deque

import psutil
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy,
    QGraphicsDropShadowEffect, QSystemTrayIcon, QMenu,
)
from PyQt6.QtCore  import Qt, QTimer, QRectF, QPointF, QLoggingCategory
from PyQt6.QtGui   import (
    QPainter, QColor, QPen, QFont, QPainterPath,
    QLinearGradient, QRadialGradient, QBrush, QPalette,
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

# Hardware vendor brand colors
NVIDIA_GREEN = "#76b900"
AMD_RED      = "#ed1c24"
INTEL_BLUE   = "#0071c5"

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

def _cpu_vendor_color() -> str:
    name = _get_cpu_name().upper()
    if any(k in name for k in ("AMD", "RYZEN", "EPYC", "ATHLON", "THREADRIPPER")):
        return AMD_RED
    if any(k in name for k in ("INTEL", "CORE", "XEON", "PENTIUM", "CELERON", "I3", "I5", "I7", "I9")):
        return INTEL_BLUE
    return CYAN

def _gpu_vendor_color() -> str:
    if GPU_HANDLE:   return NVIDIA_GREEN
    if _AMD_DEV:     return AMD_RED
    if _INTEL_DEV:   return INTEL_BLUE
    return PURPLE

CPU_COLOR = _cpu_vendor_color()
GPU_COLOR = _gpu_vendor_color()

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
    _HALOS = ((10, 8), (7, 20), (5, 38))

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

        # ── Outer bezel — dark frame ring that gives the gauge depth ─────
        bezel_rect = rect.adjusted(-5, -5, 5, 5)
        bezel_grad = QRadialGradient(cx, cy, r2 + 5)
        bezel_grad.setColorAt(0,   QColor("#141624"))
        bezel_grad.setColorAt(0.8, QColor("#09090f"))
        bezel_grad.setColorAt(1.0, QColor("#040406"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bezel_grad))
        p.drawEllipse(bezel_rect)
        # Thin metallic outer edge
        p.setPen(QPen(QColor(55, 60, 85, 110), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(bezel_rect)
        # Accent inner trim where bezel meets face
        trim = QColor(col); trim.setAlpha(28)
        p.setPen(QPen(trim, 1.0))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))

        # ── Gauge face — very dark, near-black with subtle depth ─────────
        face_grad = QRadialGradient(cx, cy - r2 * 0.15, r2)
        face_grad.setColorAt(0,    QColor("#0d1020"))
        face_grad.setColorAt(0.55, QColor("#080a13"))
        face_grad.setColorAt(1.0,  QColor("#030406"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(face_grad))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))
        # Glass highlight — very faint white sheen at the top
        hi = QRadialGradient(cx, cy - r2 * 0.55, r2 * 0.5)
        hi.setColorAt(0, QColor(255, 255, 255, 12))
        hi.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(hi))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))
        # Inner vignette — darkens face edges for a concave look
        vig = QRadialGradient(cx, cy, r2 * 0.72)
        vig.setColorAt(0,   QColor(0, 0, 0, 0))
        vig.setColorAt(0.6, QColor(0, 0, 0, 0))
        vig.setColorAt(1.0, QColor(0, 0, 0, 70))
        p.setBrush(QBrush(vig))
        p.drawEllipse(rect.adjusted(1, 1, -1, -1))
        p.setBrush(Qt.BrushStyle.NoBrush)

        # ── Arc track (inset so tick marks have room in the outer ring) ───
        inset    = 12
        trk_w    = 6
        arc_rect = rect.adjusted(inset, inset, -inset, -inset)
        arc_r2   = r2 - inset
        trk = QPen(QColor("#0d1020"), trk_w); trk.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(trk); p.drawArc(arc_rect, a0, a_end)

        # ── Tick marks in the ring between face rim and arc track ─────────
        t_outer = r2 - 2.5
        for i in range(21):        # 0..20 → every 5% → majors at 0,25,50,75,100
            t       = i / 20.0
            is_maj  = (i % 5 == 0)
            ang_rad = math.radians(self._DEG_START + self._DEG_SPAN * t)
            ca, sa  = math.cos(ang_rad), math.sin(ang_rad)
            t_len   = 6.5 if is_maj else 3.5
            t_inner = t_outer - t_len
            if is_maj:
                tc = QColor(col) if t <= pct + 0.03 else QColor(TXT_LO)
                tc.setAlpha(190)
                pw = 1.5
            else:
                tc = QColor(TXT_LO); tc.setAlpha(80)
                pw = 1.0
            p.setPen(QPen(tc, pw, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawLine(QPointF(cx + t_outer * ca, cy - t_outer * sa),
                       QPointF(cx + t_inner * ca, cy - t_inner * sa))

        # ── Colored fill arc + glow ───────────────────────────────────────
        if pct > 5e-3:
            for pw, al in self._HALOS:
                c = QColor(col); c.setAlpha(al)
                pk = QPen(c, pw); pk.setCapStyle(Qt.PenCapStyle.FlatCap)
                p.setPen(pk); p.drawArc(arc_rect, a0, a_val)
            pk = QPen(col, trk_w); pk.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pk); p.drawArc(arc_rect, a0, a_val)

            tip_ang = math.radians(self._DEG_START + self._DEG_SPAN * pct)
            tip_x   = cx + arc_r2 * math.cos(tip_ang)
            tip_y   = cy - arc_r2 * math.sin(tip_ang)
            for dr, da in ((8, 18), (5, 60), (2.5, 240)):
                c = QColor(col); c.setAlpha(da)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
                p.drawEllipse(QPointF(tip_x, tip_y), dr, dr)
            p.setBrush(Qt.BrushStyle.NoBrush)

        # ── Needle — drawn BEFORE text so value stays readable on top ────
        n_ang = math.radians(self._DEG_START + self._DEG_SPAN * pct)
        n_r   = arc_r2 - trk_w / 2 - 1
        n_tx  = cx + n_r * math.cos(n_ang)
        n_ty  = cy - n_r * math.sin(n_ang)
        # Hub glow (behind text)
        for dr, da in ((7, 30), (4.5, 80), (2.5, 200)):
            c = QColor(col); c.setAlpha(da)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
            p.drawEllipse(QPointF(cx, cy), dr, dr)
        # Needle line (behind text)
        p.setPen(QPen(QColor(col), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(cx, cy), QPointF(n_tx, n_ty))
        p.setBrush(Qt.BrushStyle.NoBrush)

        # ── Value text — shifted below hub so the needle doesn't cross it ─
        # Text rect starts at cy so the hub (at cy) is above the glyphs.
        val_str = f"{self._cur:.0f}{self._unit}"
        fs = max(10, int(side * 0.22 * (4 / max(len(val_str), 4))))
        p.setFont(_font(fs, bold=True)); p.setPen(QColor(TXT_HI))
        p.drawText(QRectF(0, cy, W, side * 0.28),
                   Qt.AlignmentFlag.AlignCenter, val_str)

        p.setFont(_font(max(8, int(side * 0.085)))); p.setPen(QColor(TXT_HI))
        p.drawText(QRectF(0, cy + side * 0.28, W, side * 0.14),
                   Qt.AlignmentFlag.AlignCenter, self._label)

        # Hub cap — drawn last so the tiny center dot is always crisp
        p.setBrush(QBrush(QColor(CARD_BG)))
        p.setPen(QPen(QColor(col), 0.8))
        p.drawEllipse(QPointF(cx, cy), 3.5, 3.5)
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
            # Position beside cursor (not above the vertical line) so it
            # doesn't obscure the data point or the hover line.
            off = 10
            if hp.x() + off + bw < W:
                bx = hp.x() + off
            else:
                bx = max(0.0, hp.x() - bw - off)
            by  = max(2.0, min(hp.y() - bh - 6, float(H - bh - 2)))
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

        # Base fill
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(CARD_BG)))
        p.drawRoundedRect(r, R, R)

        # Top gradient — dark blue-grey tint that fades to transparent
        top_grad = QLinearGradient(0, r.y(), 0, r.y() + 90)
        top_grad.setColorAt(0, QColor("#181c2e"))
        top_grad.setColorAt(1, QColor(0, 0, 0, 0))
        p.setBrush(QBrush(top_grad))
        p.drawRoundedRect(r, R, R)

        # Bottom darkening for depth
        bot_grad = QLinearGradient(0, r.bottom() - 50, 0, r.bottom())
        bot_grad.setColorAt(0, QColor(0, 0, 0, 0))
        bot_grad.setColorAt(1, QColor(0, 0, 0, 50))
        p.setBrush(QBrush(bot_grad))
        p.drawRoundedRect(r, R, R)

        # Glass sheen — very faint white shimmer at the top edge
        sheen = QLinearGradient(0, r.y(), 0, r.y() + 28)
        sheen.setColorAt(0, QColor(255, 255, 255, 16))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        p.setBrush(QBrush(sheen))
        p.drawRoundedRect(r, R, R)

        # Outer border — uniform dark blue-grey, slightly lighter at top
        border_grad = QLinearGradient(0, r.y(), 0, r.bottom())
        border_grad.setColorAt(0, QColor("#2e3248"))
        border_grad.setColorAt(1, QColor("#181b28"))
        p.setPen(QPen(QBrush(border_grad), 1.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, R, R)
        p.end()


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
            lb.setStyleSheet(f"color: {TXT_HI}; background: transparent;")
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
    def __init__(self, parent_win, cpu_color=None, gpu_color=None):
        super().__init__(parent_win)
        self._win = parent_win
        self._last_press_ms = 0.0
        self._press_pos = None  # set when docked+pressed; cleared on release/drag/dblclick
        self.setFixedHeight(52)
        self.setStyleSheet("background: transparent;")
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0); lay.setSpacing(0)

        # App icon with black border circle
        icon_path = os.path.join(_SCRIPT_DIR, "assets", "icon.png")
        if os.path.exists(icon_path):
            src = QPixmap(icon_path).scaled(
                26, 26,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            bordered = QPixmap(34, 34)
            bordered.fill(Qt.GlobalColor.transparent)
            bp = QPainter(bordered)
            bp.setRenderHint(QPainter.RenderHint.Antialiasing)
            bp.setPen(Qt.PenStyle.NoPen)
            bp.setBrush(QBrush(QColor(0, 0, 0, 170)))
            bp.drawEllipse(QRectF(0, 0, 34, 34))
            bp.drawPixmap(4, 4, src)
            bp.end()
            icon_lbl = QLabel()
            icon_lbl.setPixmap(bordered)
            icon_lbl.setFixedSize(34, 34)
            icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            icon_lbl.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            lay.addWidget(icon_lbl)
            lay.addSpacing(8)

        title = QLabel("HEATSYNC")
        title.setFont(_font(17, bold=True))
        title.setStyleSheet(f"color: {CYAN}; letter-spacing: 3px; background: transparent;")

        ver_lbl = QLabel(VERSION)
        ver_lbl.setFont(_font(10))
        ver_lbl.setStyleSheet(f"color: {TXT_HI}; background: transparent;")
        ver_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        # CPU + GPU names stacked vertically — vendor brand colors
        cpu_name  = _get_cpu_name()
        cpu_col   = cpu_color or TXT_MID
        gpu_col   = gpu_color or TXT_MID
        hw_box = QWidget()
        hw_box.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        hw_box.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        hw_v = QVBoxLayout(hw_box)
        hw_v.setContentsMargins(10, 0, 0, 0); hw_v.setSpacing(1)
        for hw_text, hw_col in ((cpu_name, cpu_col), (GPU_NAME, gpu_col)):
            lbl = QLabel(hw_text)
            lbl.setFont(_font(11))
            lbl.setStyleSheet(f"color: {hw_col}; background: transparent;")
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            hw_v.addWidget(lbl)

        self._clk = QLabel()
        self._clk.setFont(_font(14))
        self._clk.setStyleSheet(f"color: {TXT_HI}; background: transparent;")
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
        now  = datetime.now()
        hour = now.hour % 12 or 12   # 12-hour, no leading zero
        self._clk.setText(now.strftime(f"{hour}:%M:%S %p   %a %d %b %Y"))

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
        self.setMinimumSize(880, 520)
        self.resize(1080, 540)
        self._restore_pos()

        self._docked        = False
        self._pre_dock_geom = None
        self._dock_info     = None   # set by toggle_dock() at dock time
        self._last_pos      = None   # updated by moveEvent; used in _save_pos

        cw = _Background()
        self.setCentralWidget(cw)

        root = QVBoxLayout(cw)
        root.setContentsMargins(14, 8, 14, 12); root.setSpacing(8)

        self._title_bar = TitleBar(self, cpu_color=CPU_COLOR, gpu_color=GPU_COLOR)
        root.addWidget(self._title_bar)

        div = QFrame(); div.setFixedHeight(1)
        div.setStyleSheet(f"background: {CARD_BD}; border: none;")
        root.addWidget(div)

        row = QHBoxLayout(); row.setSpacing(12)
        self._cu = MonitorCard("CPU USAGE", "%",   0, 100, CPU_COLOR, 70, 90)
        self._ct = MonitorCard("CPU TEMP",  "°C",  0, 105, CPU_COLOR, 80, 95)
        self._gu = MonitorCard("GPU USAGE", "%",   0, 100, GPU_COLOR, 70, 90)
        self._gt = MonitorCard("GPU TEMP",  "°C",  0,  95, GPU_COLOR, 75, 88)
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
            self._tray_toggle_action = menu.addAction("Hide HeatSync")
            self._tray_toggle_action.triggered.connect(self._toggle_visibility)
            menu.addSeparator()
            menu.addAction("Quit").triggered.connect(QApplication.instance().quit)
            menu.aboutToShow.connect(self._update_tray_menu)
            self._tray.setContextMenu(menu)
            self._tray.show()
        else:
            self._tray = None
            print("[INFO] No system tray available — close button will quit.")

        if IS_WAYLAND:
            QTimer.singleShot(600, self._kwin_skip_taskbar)

        QApplication.instance().aboutToQuit.connect(self._save_pos)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Enforce minimum size on frameless Wayland windows — the compositor
        # may allow resizing below the hint when there are no decorations.
        mw, mh = self.minimumWidth(), self.minimumHeight()
        if self.width() < mw or self.height() < mh:
            self.resize(max(self.width(), mw), max(self.height(), mh))

    def _restore_pos(self):
        """Load saved geometry from disk into _pending_restore.
        Also preloads _dock_info so _save_pos() has correct dock coords
        even before the user manually clicks the dock button."""
        self._pending_restore = None
        try:
            with open(_SETTINGS_FILE) as f:
                d = json.load(f)
            if d.get("x") is not None and d.get("y") is not None:
                self._pending_restore = d
            if d.get("docked") and d.get("dock_x") is not None:
                self._dock_info = {
                    "dock_x": d["dock_x"],
                    "dock_y": d["dock_y"],
                    "dock_w": d.get("dock_w"),
                }
        except Exception:
            pass

    def moveEvent(self, event):
        super().moveEvent(event)
        p = event.pos()
        # Ignore (0,0) — Wayland "not yet positioned" sentinel.
        if p.x() == 0 and p.y() == 0:
            return
        self._last_pos = (p.x(), p.y())
        # Auto-undock if the window moved significantly away from its dock
        # position (user dragged without clicking the undock button).
        # Comparing against _dock_info avoids false-triggering on the
        # configure event that KWin sends after _kwin_set_geometry (which
        # would land at exactly the dock_x/dock_y we requested).
        if self._docked and self._dock_info:
            dock_x = self._dock_info.get("dock_x", p.x())
            dock_y = self._dock_info.get("dock_y", p.y())
            if abs(p.x() - dock_x) > 50 or abs(p.y() - dock_y) > 50:
                self._docked = False
                cw = self.centralWidget()
                if isinstance(cw, _Background):
                    cw.set_squared(False)
                self._title_bar.dock_btn.set_active(False)

    def showEvent(self, event):
        super().showEvent(event)
        d = self._pending_restore
        if not d:
            return
        self._pending_restore = None
        self._apply_state(d, first_show=True)

    def _apply_state(self, d, first_show=True):
        """Apply saved geometry + dock state from a settings dict.

        Uses _kwin_set_geometry (Wayland) to set position AND size atomically
        in a single KWin script call, bypassing Qt's Wayland resize quirks.
        Never calls toggle_dock() — that would re-query self.screen() which
        may return the wrong screen after a KWin move.

        first_show=True  → 700 ms delay (window being mapped for the first time)
        first_show=False → 500 ms delay (re-show after tray hide; already known to KWin)
        """
        docked = d.get("docked", False)
        x, y   = d.get("x"), d.get("y")
        w, h   = d.get("w"), d.get("h")
        dock_x = d.get("dock_x", x)
        dock_y = d.get("dock_y", y)
        dock_w = d.get("dock_w", w)
        delay  = 700 if first_show else 500

        def apply():
            if docked:
                dw = dock_w or w or self.width()
                dh = h or self.height()
                if IS_WAYLAND:
                    self._kwin_set_geometry(dock_x, dock_y, dw, dh)
                else:
                    self.resize(dw, dh)
                    self.move(dock_x, dock_y)
                # Restore docked UI state if not already set.
                if not self._docked:
                    self._docked = True
                    cw = self.centralWidget()
                    if isinstance(cw, _Background):
                        cw.set_squared(True)
                    self._title_bar.dock_btn.set_active(True)
            else:
                if w and h:
                    self.resize(w, h)
                if x is not None and y is not None:
                    if IS_WAYLAND:
                        self._kwin_move(x, y)
                    else:
                        self.move(x, y)
                    # Seed _last_pos so _save_pos() has accurate coords on
                    # first hide even before the user drags the window.
                    self._last_pos = (x, y)

        QTimer.singleShot(delay if IS_WAYLAND else 0, apply)

    def _save_pos(self):
        try:
            g = self.geometry()
            # Prefer _last_pos (from moveEvent configure events) over geometry()
            # because geometry() is stale on Wayland after startSystemMove().
            if self._last_pos:
                px, py = self._last_pos
            else:
                px, py = g.x(), g.y()
            data = {
                "x": px, "y": py,
                "w": g.width(), "h": g.height(),
                "docked": self._docked,
            }
            if self._docked and self._dock_info:
                # Use coordinates captured at dock time — self.screen() can
                # report the wrong screen at quit time on Wayland.
                data.update(self._dock_info)
            with open(_SETTINGS_FILE, "w") as f:
                json.dump(data, f)
        except Exception:
            pass

    def _update_tray_menu(self):
        self._tray_toggle_action.setText(
            "Hide HeatSync" if self.isVisible() else "Show HeatSync"
        )

    def closeEvent(self, e):
        if self._tray and self._tray.isVisible():
            self._save_pos()
            self.hide(); e.ignore()
        else:
            self._save_pos()
            e.accept()

    def _toggle_visibility(self):
        if self.isVisible():
            self._save_pos()
            self.hide()
        else:
            self.show(); self.raise_(); self.activateWindow()
            if IS_WAYLAND:
                QTimer.singleShot(400, self._kwin_skip_taskbar)
                # On Wayland, KWin repositions the window on every re-show.
                # Restore saved position/dock directly (no toggle_dock recalc).
                # X11/Windows preserve position on hide/show — no action needed.
                try:
                    with open(_SETTINGS_FILE) as f:
                        self._apply_state(json.load(f), first_show=False)
                except Exception:
                    pass

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

    def _kwin_set_geometry(self, x: int, y: int, w: int, h: int) -> bool:
        """Set HeatSync position AND size atomically via KWin scripting.
        Bypasses Qt's Wayland resize quirks by going straight to the compositor."""
        return self._kwin_run(
            f"var wins = workspace.windowList();"
            f"for (var i = 0; i < wins.length; i++) {{"
            f"  if (wins[i].resourceClass === 'heatsync') {{"
            f"    wins[i].frameGeometry = {{x:{x}, y:{y}, width:{w}, height:{h}}};"
            f"    break;"
            f"  }}"
            f"}}",
            tag="hs_geom",
        )

    # ── Dock toggle ───────────────────────────────────────────────────────────
    def toggle_dock(self, via_drag: bool = False):
        cw = self.centralWidget()
        if not self._docked:
            self._pre_dock_geom = self.geometry()
            ag = self.screen().availableGeometry()
            tx, ty = ag.x(), ag.y()
            self.resize(ag.width(), self.height())
            # Capture dock coordinates now — self.screen() is reliable here.
            self._dock_info = {"dock_x": tx, "dock_y": ty, "dock_w": ag.width()}
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
        # Qt warns when heatsync.desktop isn't found in system paths (harmless).
        QLoggingCategory.setFilterRules("qt.qpa.services.warning=false")
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
