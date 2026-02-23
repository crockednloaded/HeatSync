#!/home/mack3y/.sysmon_venv/bin/python
"""
System Monitor — NZXT CAM-style
CachyOS · AMD Ryzen 9 9800X3D · NVIDIA GeForce RTX 5070 Ti
"""

import sys
import os
import math
import warnings
from datetime import datetime

# Re-exec under the venv if pynvml isn't importable
_VENV_PY = os.path.expanduser("~/.sysmon_venv/bin/python")
if sys.executable != _VENV_PY and os.path.exists(_VENV_PY):
    try:
        import pynvml  # noqa: F401
    except ImportError:
        os.execv(_VENV_PY, [_VENV_PY] + sys.argv)
from collections import deque

import psutil
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QFrame, QSizePolicy,
    QGraphicsDropShadowEffect,
)
from PyQt6.QtCore  import Qt, QTimer, QRectF, QPointF
from PyQt6.QtGui   import (
    QPainter, QColor, QPen, QFont, QPainterPath,
    QLinearGradient, QRadialGradient, QBrush, QPalette,
)

# ── NVIDIA init ──────────────────────────────────────────────────────────────
GPU_HANDLE = None
GPU_NAME   = "GPU Unavailable"
try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        import pynvml
    pynvml.nvmlInit()
    GPU_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
    _n = pynvml.nvmlDeviceGetName(GPU_HANDLE)
    GPU_NAME = _n.decode() if isinstance(_n, bytes) else _n
except Exception as _gpu_exc:
    print(f"[WARN] GPU monitoring unavailable: {_gpu_exc}")

# ── Palette ──────────────────────────────────────────────────────────────────
BG       = "#090b10"
CARD_BG  = "#0e1018"
CARD_BD  = "#1a1d2b"
TXT_HI   = "#e5e8f0"
TXT_MID  = "#848ba0"
TXT_LO   = "#404560"

CYAN   = "#00ccdd"   # CPU usage
GREEN  = "#00e676"   # CPU temp
PURPLE = "#9d6fff"   # GPU usage
AMBER  = "#ffa040"   # GPU temp
C_WARN = "#ff9800"
C_DANG = "#f44336"

TRACK_COL = QColor("#141724")

# ── Font helper ──────────────────────────────────────────────────────────────
_FONT_FAMILIES = ["JetBrainsMono NF", "JetBrainsMono Nerd Font", "JetBrains Mono",
                  "Hack", "Fira Sans", "Sans Serif"]

def _font(px: int, bold: bool = False) -> QFont:
    f = QFont()
    f.setFamilies(_FONT_FAMILIES)
    f.setPixelSize(max(8, int(px)))
    if bold:
        f.setWeight(QFont.Weight.Bold)
    return f

# ── Sensors ──────────────────────────────────────────────────────────────────
psutil.cpu_percent()   # prime — first call is always 0.0

def s_cpu_usage() -> float:
    return psutil.cpu_percent()

def s_cpu_temp() -> float:
    try:
        temps = psutil.sensors_temperatures()
        for key in ("k10temp", "zenpower", "coretemp"):
            if key not in temps:
                continue
            entries = temps[key]
            tctl = next(
                (e.current for e in entries
                 if e.label in ("Tctl", "Package id 0", "Tdie")),
                None,
            )
            return tctl if tctl is not None else entries[0].current
    except Exception:
        pass
    return 0.0

def s_gpu_usage() -> float:
    if not GPU_HANDLE:
        return 0.0
    try:
        return float(pynvml.nvmlDeviceGetUtilizationRates(GPU_HANDLE).gpu)
    except Exception:
        return 0.0

def s_gpu_temp() -> float:
    if not GPU_HANDLE:
        return 0.0
    try:
        return float(pynvml.nvmlDeviceGetTemperature(
            GPU_HANDLE, pynvml.NVML_TEMPERATURE_GPU))
    except Exception:
        return 0.0

def s_gpu_vram():
    """Returns (used_MB, total_MB)."""
    if not GPU_HANDLE:
        return 0, 0
    try:
        m = pynvml.nvmlDeviceGetMemoryInfo(GPU_HANDLE)
        return m.used >> 20, m.total >> 20
    except Exception:
        return 0, 0

def s_ram():
    """Returns (used_GB, total_GB)."""
    v = psutil.virtual_memory()
    return v.used / 1e9, v.total / 1e9

def s_cpu_freq() -> float:
    """Returns current freq in GHz."""
    f = psutil.cpu_freq()
    return f.current / 1000.0 if f else 0.0

# ── Arc Gauge ────────────────────────────────────────────────────────────────
class ArcGauge(QWidget):
    """
    Near-full circle arc gauge (300° sweep, 60° gap at bottom).

    Arc sweeps clockwise from ~7-o'clock to ~5-o'clock,
    matching the minimal ring style seen in modern system monitors.
    """
    _DEG_START = 240   # 7-o'clock position (Qt CCW from 3-o'clock)
    _DEG_SPAN  = -300  # CW sweep → 300° arc, 60° gap at bottom

    # Thin glow stack: (pen_width, alpha) outer→inner — much softer than before
    _HALOS = ((14, 10), (9, 22), (6, 40))

    def __init__(
        self,
        label: str,
        unit: str,
        lo: float = 0,
        hi: float = 100,
        color: str = CYAN,
        warn: float = 75,
        danger: float = 90,
    ):
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

        tmr = QTimer(self)
        tmr.timeout.connect(self._tick)
        tmr.start(15)   # ~66 fps

    def set_value(self, v: float) -> None:
        self._target = max(self._lo, min(self._hi, v))

    def _tick(self) -> None:
        delta = self._target - self._cur
        if abs(delta) > 0.02:
            self._cur += delta * 0.13   # exponential ease
            self.update()
        elif self._cur != self._target:
            self._cur = self._target
            self.update()

    def _active_col(self) -> QColor:
        span = max(self._hi - self._lo, 1e-9)
        pct  = (self._cur - self._lo) / span * 100
        if pct >= self._danger:
            return self._c_dang
        if pct >= self._warn:
            return self._c_warn
        return self._col

    def paintEvent(self, _event) -> None:
        W, H = self.width(), self.height()
        margin = 22
        side   = min(W, H) - margin * 2
        rx     = (W - side) / 2
        ry     = (H - side) / 2 - 8        # push arc slightly above centre for label room
        rect   = QRectF(rx, ry, side, side)
        r2     = side / 2
        arc_cx = rx + r2
        arc_cy = ry + r2

        a0    = self._DEG_START * 16
        a_end = self._DEG_SPAN  * 16
        span  = max(self._hi - self._lo, 1e-9)
        pct   = max(0.0, min(1.0, (self._cur - self._lo) / span))
        a_val = int(a_end * pct)
        col   = self._active_col()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(Qt.BrushStyle.NoBrush)

        # ── Track ring ────────────────────────────────────────────────────
        trk = QPen(QColor("#1c1f2e"), 3)
        trk.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(trk)
        p.drawArc(rect, a0, a_end)

        if pct > 5e-3:
            # ── Soft outer glow layers ────────────────────────────────────
            for pw, al in self._HALOS:
                c = QColor(col); c.setAlpha(al)
                pk = QPen(c, pw); pk.setCapStyle(Qt.PenCapStyle.FlatCap)
                p.setPen(pk); p.drawArc(rect, a0, a_val)

            # ── Crisp core arc ─────────────────────────────────────────────
            pk = QPen(col, 3); pk.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pk); p.drawArc(rect, a0, a_val)

            # ── Glowing tip dot ───────────────────────────────────────────
            tip_ang = math.radians(self._DEG_START + self._DEG_SPAN * pct)
            tip_x   = arc_cx + r2 * math.cos(tip_ang)
            tip_y   = arc_cy - r2 * math.sin(tip_ang)
            for dot_r, dot_al in ((8, 15), (5, 50), (2.5, 230)):
                c = QColor(col); c.setAlpha(dot_al)
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
                p.drawEllipse(QPointF(tip_x, tip_y), dot_r, dot_r)
            p.setBrush(Qt.BrushStyle.NoBrush)

        # ── Centre: value + unit on one line ──────────────────────────────
        val_str = f"{self._cur:.0f}{self._unit}"
        # Tint value text slightly towards accent colour
        blend   = 0.25
        val_col = QColor(
            min(255, int(229 * (1 - blend) + col.red()   * blend)),
            min(255, int(232 * (1 - blend) + col.green() * blend)),
            min(255, int(240 * (1 - blend) + col.blue()  * blend)),
        )
        # Auto-size font so longer strings (e.g. "100°C") still fit
        fs = max(10, int(side * 0.22 * (4 / max(len(val_str), 4))))
        vf = _font(fs, bold=True)
        p.setFont(vf); p.setPen(val_col)
        p.drawText(
            QRectF(0, arc_cy - side * 0.17, W, side * 0.34),
            Qt.AlignmentFlag.AlignCenter, val_str,
        )

        # ── Label ─────────────────────────────────────────────────────────
        lf = _font(max(8, int(side * 0.085)))
        p.setFont(lf); p.setPen(QColor(TXT_MID))
        p.drawText(
            QRectF(0, arc_cy + side * 0.20, W, side * 0.18),
            Qt.AlignmentFlag.AlignCenter, self._label,
        )

        p.end()


# ── Sparkline ────────────────────────────────────────────────────────────────
class Sparkline(QWidget):
    """Smooth cubic-bezier area sparkline with gradient fill."""

    def __init__(self, color: str = CYAN, max_pts: int = 90):
        super().__init__()
        self._col  = QColor(color)
        self._hist: deque[float] = deque(maxlen=max_pts)
        self.setFixedHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def push(self, v: float) -> None:
        self._hist.append(v)
        self.update()

    def paintEvent(self, _event) -> None:
        if len(self._hist) < 2:
            return
        W, H = self.width(), self.height()
        px, py = 3, 6
        vals = list(self._hist)
        hi   = max(max(vals), 1.0)
        n    = len(vals)

        def fx(i: int) -> float:
            return px + i / (n - 1) * (W - 2 * px)

        def fy(v: float) -> float:
            return H - py - v / hi * (H - 2 * py)

        pts = [QPointF(fx(i), fy(v)) for i, v in enumerate(vals)]

        # Smooth cubic bezier through all points
        line = QPainterPath()
        line.moveTo(pts[0])
        for i in range(1, n):
            mid_x = (pts[i - 1].x() + pts[i].x()) / 2
            line.cubicTo(
                QPointF(mid_x, pts[i - 1].y()),
                QPointF(mid_x, pts[i].y()),
                pts[i],
            )

        # Closed fill area
        area = QPainterPath(line)
        area.lineTo(QPointF(pts[-1].x(), H))
        area.lineTo(QPointF(pts[0].x(),  H))
        area.closeSubpath()

        grad = QLinearGradient(0, 0, 0, H)
        top = QColor(self._col); top.setAlpha(55)
        bot = QColor(self._col); bot.setAlpha(0)
        grad.setColorAt(0.0, top)
        grad.setColorAt(1.0, bot)

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillPath(area, QBrush(grad))
        p.setPen(QPen(
            self._col, 1.7,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        ))
        p.drawPath(line)

        # ── Glowing endpoint dot (current value) ─────────────────────────
        tip = pts[-1]
        for dot_r, dot_al in ((7, 18), (4.5, 60), (2.5, 240)):
            c = QColor(self._col); c.setAlpha(dot_al)
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QBrush(c))
            p.drawEllipse(tip, dot_r, dot_r)

        p.end()


# ── Monitor Card ─────────────────────────────────────────────────────────────
class MonitorCard(QFrame):
    """Rounded card with hand-painted background, accent gradient, and shadow."""

    _R = 18.0

    def __init__(
        self,
        label: str,
        unit: str,
        lo: float = 0,
        hi: float = 100,
        color: str = CYAN,
        warn: float = 75,
        danger: float = 90,
    ):
        super().__init__()
        self._accent = QColor(color)

        self.gauge = ArcGauge(label, unit, lo, hi, color, warn, danger)
        self.spark = Sparkline(color)

        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {CARD_BD}; border: none; border-radius: 0;")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 14, 10, 10)
        lay.setSpacing(8)
        lay.addWidget(self.gauge, 1)
        lay.addWidget(sep)
        lay.addWidget(self.spark)

        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(28)
        sh.setColor(QColor(0, 0, 0, 160))
        sh.setOffset(0, 5)
        self.setGraphicsEffect(sh)

    def push(self, v: float) -> None:
        self.gauge.set_value(v)
        self.spark.push(v)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        R = self._R

        # ── Base fill ──────────────────────────────────────────────────
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(CARD_BG)))
        p.drawRoundedRect(r, R, R)

        # ── Top accent gradient (colour-matched glow wash) ──────────────
        grad = QLinearGradient(0, 0, 0, 72)
        c0 = QColor(self._accent); c0.setAlpha(38)
        c1 = QColor(self._accent); c1.setAlpha(0)
        grad.setColorAt(0, c0); grad.setColorAt(1, c1)
        p.setBrush(QBrush(grad))
        p.drawRoundedRect(r, R, R)

        # ── Outer border — faint accent tint ───────────────────────────
        border_c = QColor(self._accent); border_c.setAlpha(55)
        p.setPen(QPen(border_c, 1))
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
        lay.setContentsMargins(6, 0, 6, 0)
        lay.setSpacing(32)

        self._lbs: dict[str, QLabel] = {}
        for key in ("RAM", "VRAM", "CPU Freq", "Threads"):
            lb = QLabel(f"{key}: –")
            lb.setFont(_font(12))
            lb.setStyleSheet(f"color: {TXT_MID}; background: transparent;")
            self._lbs[key] = lb
            lay.addWidget(lb)

        lay.addStretch()

    def refresh(self) -> None:
        used_r, tot_r = s_ram()
        self._lbs["RAM"].setText(f"RAM  {used_r:.1f} / {tot_r:.0f} GB")

        used_v, tot_v = s_gpu_vram()
        if tot_v:
            self._lbs["VRAM"].setText(f"VRAM  {used_v:,} / {tot_v:,} MB")
        else:
            self._lbs["VRAM"].setText("VRAM  N/A")

        ghz = s_cpu_freq()
        self._lbs["CPU Freq"].setText(f"CPU Freq  {ghz:.2f} GHz")

        cores = psutil.cpu_count(logical=True)
        self._lbs["Threads"].setText(f"Threads  {cores}")


# ── Window control button ─────────────────────────────────────────────────────
class _WinBtn(QWidget):
    """Small circular button for close/minimize."""
    def __init__(self, symbol: str, color: str, callback):
        super().__init__()
        self._symbol  = symbol
        self._color   = QColor(color)
        self._dim     = QColor(color).darker(140)
        self._cb      = callback
        self._hovered = False
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def enterEvent(self, _e):
        self._hovered = True;  self.update()

    def leaveEvent(self, _e):
        self._hovered = False; self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._cb()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self._color if self._hovered else self._dim)
        p.drawEllipse(0, 0, 16, 16)
        if self._hovered:
            p.setFont(_font(9, bold=True))
            p.setPen(QColor(0, 0, 0, 210))
            p.drawText(QRectF(0, 0, 16, 16), Qt.AlignmentFlag.AlignCenter, self._symbol)
        p.end()


# ── Dock-to-top button ───────────────────────────────────────────────────────
class _DockBtn(QWidget):
    """Draws a 'panel docked at top of screen' icon; toggles active state."""

    def __init__(self, callback):
        super().__init__()
        self._cb      = callback
        self._active  = False
        self._hovered = False
        self.setFixedSize(26, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_active(self, v: bool) -> None:
        self._active = v; self.update()

    def enterEvent(self, _e): self._hovered = True;  self.update()
    def leaveEvent(self, _e): self._hovered = False; self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._cb()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        rim_c = QColor(CYAN) if (self._active or self._hovered) else QColor(TXT_LO)

        # Screen outline
        p.setPen(QPen(rim_c, 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, H - 1), 2.5, 2.5)

        # Docked bar at top (filled when active)
        bar_c = QColor(CYAN if self._active else rim_c.name())
        bar_c.setAlpha(220 if self._active else (160 if self._hovered else 90))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(bar_c))
        p.drawRoundedRect(QRectF(0.5, 0.5, W - 1, 5), 2.5, 2.5)
        p.end()


# ── Resize grip ───────────────────────────────────────────────────────────────
class ResizeGrip(QWidget):
    """Bottom-right corner resize handle using compositor system-resize."""

    def __init__(self, parent_win: QMainWindow):
        super().__init__(parent_win)
        self._win = parent_win
        self.setFixedSize(22, 22)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._win.windowHandle()
            if handle:
                handle.startSystemResize(
                    Qt.Edge.RightEdge | Qt.Edge.BottomEdge
                )

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(TXT_LO), 1.5, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        # Three diagonal tick marks
        for i in range(3):
            o = 5 + i * 5
            p.drawLine(o, 20, 20, o)
        p.end()


# ── Title / Drag Bar ──────────────────────────────────────────────────────────
class TitleBar(QWidget):
    """Frameless drag bar: click-drag calls startSystemMove (Wayland + X11 safe)."""

    def __init__(self, parent_win: QMainWindow):
        super().__init__(parent_win)
        self._win = parent_win

        self.setFixedHeight(52)
        self.setStyleSheet("background: transparent;")
        self.setCursor(Qt.CursorShape.SizeAllCursor)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 0, 14, 0)
        lay.setSpacing(0)

        title = QLabel("◈  SYSTEM MONITOR")
        title.setFont(_font(17, bold=True))
        title.setStyleSheet(
            f"color: {CYAN}; letter-spacing: 3px; background: transparent;"
        )

        sep_dot = QLabel("  ·  ")
        sep_dot.setStyleSheet(f"color: {TXT_LO}; background: transparent;")

        hw_lbl = QLabel(f"AMD Ryzen 9 9800X3D  ·  {GPU_NAME}")
        hw_lbl.setFont(_font(13))
        hw_lbl.setStyleSheet(f"color: {TXT_LO}; background: transparent;")

        self._clk = QLabel()
        self._clk.setFont(_font(14))
        self._clk.setStyleSheet(f"color: {TXT_MID}; background: transparent;")
        self._tick()
        t = QTimer(self); t.timeout.connect(self._tick); t.start(1000)

        btn_min      = _WinBtn("−", "#ffbd2e", parent_win.showMinimized)
        btn_cls      = _WinBtn("✕", "#ff5f57", parent_win.close)
        self.dock_btn = _DockBtn(parent_win.toggle_dock)
        for btn in (btn_min, btn_cls, self.dock_btn):
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        # Pass-through mouse events on all labels so drags reach this widget
        for lbl in (title, sep_dot, hw_lbl, self._clk):
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        lay.addWidget(title)
        lay.addWidget(sep_dot)
        lay.addWidget(hw_lbl)
        lay.addStretch()
        lay.addWidget(self._clk)
        lay.addSpacing(18)
        lay.addWidget(self.dock_btn)
        lay.addSpacing(10)
        lay.addWidget(btn_min)
        lay.addSpacing(8)
        lay.addWidget(btn_cls)

    def _tick(self) -> None:
        self._clk.setText(datetime.now().strftime("%H:%M:%S   %a %d %b %Y"))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            handle = self._win.windowHandle()
            if handle:
                handle.startSystemMove()
        super().mousePressEvent(event)


# ── Rounded window background ────────────────────────────────────────────────
class _Background(QWidget):
    """Paints the rounded dark background for the frameless translucent window."""
    _R = 16.0

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # Main fill
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(QColor(BG)))
        p.drawRoundedRect(r, self._R, self._R)

        # Outer rim — very subtle lighter border
        p.setPen(QPen(QColor("#1e2238"), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r, self._R, self._R)

        p.end()


# ── Main Window ──────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("System Monitor")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumSize(880, 480)
        self.resize(1080, 540)

        self._docked        = False
        self._pre_dock_geom = None

        cw = _Background()
        self.setCentralWidget(cw)

        root = QVBoxLayout(cw)
        root.setContentsMargins(14, 8, 14, 12)
        root.setSpacing(8)

        # Drag title bar (keep reference for dock button updates)
        self._title_bar = TitleBar(self)
        root.addWidget(self._title_bar)

        # Divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {CARD_BD}; border: none;")
        root.addWidget(div)

        # 4 metric cards
        row = QHBoxLayout()
        row.setSpacing(12)

        self._cu = MonitorCard("CPU USAGE", "%",   0, 100, CYAN,   70, 90)
        self._ct = MonitorCard("CPU TEMP",  "°C",  0, 105, GREEN,  80, 95)
        self._gu = MonitorCard("GPU USAGE", "%",   0, 100, PURPLE, 70, 90)
        self._gt = MonitorCard("GPU TEMP",  "°C",  0,  95, AMBER,  75, 88)

        for card in (self._cu, self._ct, self._gu, self._gt):
            row.addWidget(card)
        root.addLayout(row, 1)

        # Status bar
        div2 = QFrame()
        div2.setFixedHeight(1)
        div2.setStyleSheet(f"background: {CARD_BD}; border: none;")
        root.addWidget(div2)

        # Status bar + resize grip on the same row
        bot_row = QHBoxLayout()
        bot_row.setContentsMargins(0, 0, 0, 0)
        bot_row.setSpacing(0)
        self._sb = StatusBar()
        bot_row.addWidget(self._sb, 1)
        bot_row.addWidget(ResizeGrip(self))
        root.addLayout(bot_row)

        # Poll sensors every second
        t = QTimer(self)
        t.timeout.connect(self._refresh)
        t.start(1000)
        self._refresh()   # populate immediately on launch

    def toggle_dock(self) -> None:
        if not self._docked:
            self._pre_dock_geom = self.geometry()
            ag = self.screen().availableGeometry()
            self.setGeometry(ag.x(), ag.y(), ag.width(), self.height())
            self._docked = True
        else:
            if self._pre_dock_geom is not None:
                self.setGeometry(self._pre_dock_geom)
            self._docked = False
        self._title_bar.dock_btn.set_active(self._docked)

    def _refresh(self) -> None:
        self._cu.push(s_cpu_usage())
        self._ct.push(s_cpu_temp())
        self._gu.push(s_gpu_usage())
        self._gt.push(s_gpu_temp())
        self._sb.refresh()


# ── Entry point ──────────────────────────────────────────────────────────────
def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    # Dark palette for all Qt widgets
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
