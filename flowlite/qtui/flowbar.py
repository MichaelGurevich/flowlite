"""The Flow Bar: the floating pill at the bottom of the screen.

Rebuilt from Wispr Flow's status window (measured sizes, bottom dock):
  resting      40x8   rgba(0,0,0,.5) fill, 1px rgba(255,255,255,.5) border
  hover/ready  50x30  black, #30302f border, tooltip "Hold [Ctrl] [Win] to dictate"
  push-to-talk 73x30  white waveform bars (2px wide, 18px tall max)
  hands-free  102x30  + cancel (sand-950 circle, X) and stop (sand-50 circle, square)
  command      amber (#ffa946) border and bars
  processing   98x30  8-bar radial spinner (rgba(163,148,199))
  error        91x30  1.5px #ee6a6a border
Notifications are black rounded cards that rise above the pill.

The window is translucent (fully transparent pixels are click-through on Windows), never
takes focus (WS_EX_NOACTIVATE), and is only hit-testable where something is painted.
"""

import ctypes
import math
import time

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QMenu, QWidget

from . import theme

W, H = 520, 360          # window; the pill sits bottom-center
BOTTOM_GAP = 10
SIZES = {"hidden": (0, 0), "resting": (40, 8), "hover": (50, 30), "listening": (73, 30),
         "locked": (102, 30), "command": (73, 30), "command_locked": (102, 30),
         "processing": (98, 30), "error": (91, 30)}
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008

user32 = ctypes.windll.user32
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int)
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t)


class FlowBar(QWidget):
    # cross-thread API (controller threads emit; Qt queues onto the GUI thread)
    _state_sig = Signal(str)
    _level_sig = Signal(float)
    _flash_sig = Signal(str, float, str)
    _call_sig = Signal(object)

    clicked = Signal()            # idle: start hands-free
    cancel_clicked = Signal()
    stop_clicked = Signal()

    def __init__(self, shortcut_text="Ctrl + Win", show_resting=True):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus |
                         Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.resize(W, H)
        self.shortcut_text = shortcut_text
        self._show_resting = show_resting
        self.menu_builder = None          # callable(QMenu) -> None, set by the app

        self.state = "idle"
        self.hovering = False
        self.size = [0.0, 0.0]
        self.target = (0, 0)
        self.level = 0.0
        self.level_target = 0.0
        self.notice = None               # dict(title, subtitle, until, born)
        self.hidden_until = 0.0

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(320)
        self._anim.setEasingCurve(QEasingCurve.Type.OutBack)
        self._anim.valueChanged.connect(self._on_anim)
        self._from = (0.0, 0.0)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

        self._state_sig.connect(self._set_state)
        self._level_sig.connect(self._set_level)
        self._flash_sig.connect(self._flash)
        self._call_sig.connect(lambda fn: fn())
        self._place()
        self._retarget(animate=False)

    # ------------------------------------------------------------- public API
    def set_state(self, state):
        """idle | listening | locked | command | processing | error (thread-safe)."""
        self._state_sig.emit(state)

    def set_level(self, value):
        self._level_sig.emit(float(value))

    def flash(self, text, seconds=2.5, subtitle=""):
        self._flash_sig.emit(text, float(seconds), subtitle)

    def call(self, fn):
        self._call_sig.emit(fn)

    @property
    def show_resting(self):
        return self._show_resting

    @show_resting.setter
    def show_resting(self, value):
        self._show_resting = bool(value)
        self.call(lambda: self._retarget())

    def hide_for(self, seconds):
        self.hidden_until = time.monotonic() + seconds
        self._retarget()

    # --------------------------------------------------------------- internals
    def _place(self):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        g = screen.availableGeometry()
        self.move(g.x() + (g.width() - W) // 2, g.y() + g.height() - H)

    def _visual_state(self):
        if self.state == "idle":
            if time.monotonic() < self.hidden_until or not self._show_resting:
                return "hover" if self.hovering else "hidden"
            return "hover" if self.hovering else "resting"
        return self.state

    def _retarget(self, animate=True):
        target = SIZES.get(self._visual_state(), SIZES["listening"])
        if target == self.target and animate:
            return
        self.target = target
        if not self.isVisible() and (target != (0, 0) or self.notice):
            self.show()
            self._make_noactivate()
        if animate:
            self._from = tuple(self.size)
            self._anim.stop()
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.start()
        else:
            self.size = list(target)
        self._ensure_timer()
        self.update()

    def _on_anim(self, t):
        t = float(t)
        self.size = [self._from[0] + (self.target[0] - self._from[0]) * t,
                     max(0.0, self._from[1] + (self.target[1] - self._from[1]) * t)]
        self.update()

    def _ensure_timer(self):
        active = self.state not in ("idle",) or self.notice or self.hovering
        if active and not self._timer.isActive():
            self._timer.start()
        elif not active and self._timer.isActive() and self._anim.state() != QVariantAnimation.State.Running:
            self._timer.stop()

    def _set_state(self, state):
        if state == self.state:
            return
        if self.state == "idle" and state != "idle":
            self._place()  # follow the monitor the user is working on
        self.state = state
        if state not in ("listening", "locked", "command"):
            self.level_target = 0.0
        self._retarget()

    def _set_level(self, value):
        self.level_target = value

    def _flash(self, text, seconds, subtitle):
        self.notice = {"title": text, "subtitle": subtitle, "until": time.monotonic() + seconds,
                       "born": time.monotonic()}
        if not self.isVisible():
            self.show()
            self._make_noactivate()
        self._ensure_timer()
        self.update()

    def _tick(self):
        self.level = round(0.85 * self.level + 0.15 * self.level_target, 3)
        if self.notice and time.monotonic() > self.notice["until"]:
            self.notice = None
        if self.target == (0, 0) and not self.notice and self._anim.state() != QVariantAnimation.State.Running:
            self.hide()
        self._ensure_timer()
        self.update()

    def _make_noactivate(self):
        hwnd = int(self.winId())
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST)

    # ------------------------------------------------------------------- geometry
    def _pill_rect(self):
        w, h = self.size
        return QRectF((W - w) / 2, H - BOTTOM_GAP - h, w, h)

    def _hot_rect(self):
        # Wispr keeps a near-invisible 40px-tall hover area around the resting pill.
        return QRectF(W / 2 - 40, H - BOTTOM_GAP - 34, 80, 40)

    def _button_rects(self):
        r = self._pill_rect()
        cy = r.center().y()
        return (QRectF(r.left() + 6, cy - 9, 18, 18), QRectF(r.right() - 24, cy - 9, 18, 18))

    # --------------------------------------------------------------------- events
    def mouseMoveEvent(self, e):
        inside = self._hot_rect().contains(e.position()) or self._pill_rect().adjusted(-6, -6, 6, 6).contains(e.position())
        if inside != self.hovering:
            self.hovering = inside
            self._retarget()

    def leaveEvent(self, e):
        if self.hovering:
            self.hovering = False
            self._retarget()

    def mousePressEvent(self, e):
        pos = e.position()
        if e.button() == Qt.MouseButton.RightButton:
            self._context_menu(e.globalPosition().toPoint())
            return
        if self.state in ("locked", "command_locked"):
            cancel, stop = self._button_rects()
            if cancel.contains(pos):
                self.cancel_clicked.emit()
                return
            if stop.contains(pos):
                self.stop_clicked.emit()
                return
        if self._pill_rect().adjusted(-6, -6, 6, 6).contains(pos) or self._hot_rect().contains(pos):
            if self.state == "idle":
                self.clicked.emit()
            elif self.state in ("listening", "locked", "command"):
                self.stop_clicked.emit()

    def _context_menu(self, global_pos):
        menu = QMenu()
        menu.setStyleSheet(
            "QMenu { background: #1a1a1a; color: #fcfcfb; border: 1px solid #30302f; border-radius: 12px;"
            " padding: 6px; font-family: Figtree; font-size: 14px; }"
            " QMenu::item { padding: 8px 18px; border-radius: 7px; color: #fcfcfb; }"
            " QMenu::item:selected { background: #30302f; } QMenu::separator { height: 1px;"
            " background: #30302f; margin: 5px 8px; } QMenu::item:disabled { color: #878683; }")
        if self.menu_builder:
            self.menu_builder(menu)
        menu.exec(global_pos)

    # ---------------------------------------------------------------------- paint
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        vis = self._visual_state()
        if vis in ("resting", "hover"):
            p.fillRect(self._hot_rect(), QColor(0, 0, 0, 2))  # hit-testable hover zone
        w, h = self.size
        if w > 1 and h > 1:
            self._paint_pill(p, vis)
        if vis == "hover" and self.state == "idle" and not self.notice:
            self._paint_tooltip(p)
        if self.notice:
            self._paint_notice(p)

    def _paint_pill(self, p, vis):
        r = self._pill_rect()
        radius = r.height() / 2
        if vis == "resting":
            p.setPen(QPen(QColor(255, 255, 255, 128), 1))
            p.setBrush(QColor(0, 0, 0, 128))
            p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
            return
        border = QColor("#30302f")
        width = 1.0
        if self.state in ("command", "command_locked"):
            border, width = QColor("#ffa946"), 1.2
        elif self.state == "error":
            border, width = QColor("#ee6a6a"), 1.5
        fill = QColor("#30302f") if (vis == "hover" and self.hovering and self.state == "idle") else QColor("#000000")
        p.setPen(QPen(border, width))
        p.setBrush(fill)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)

        if self.state in ("listening", "locked", "command", "command_locked"):
            self._paint_wave(p, r)
            if self.state in ("locked", "command_locked") and r.width() > 90:
                self._paint_buttons(p)
        elif self.state == "processing":
            self._paint_spinner(p, r.center())
        elif self.state == "error":
            p.setPen(QPen(QColor("#ee6a6a"), 2))
            c = r.center()
            p.drawLine(QPointF(c.x(), c.y() - 6), QPointF(c.x(), c.y() + 2))
            p.drawPoint(QPointF(c.x(), c.y() + 6))

    def _paint_wave(self, p, r):
        bars, bw, gap = 9, 2.0, 3.0
        total = bars * bw + (bars - 1) * gap
        x0 = r.center().x() - total / 2
        cy = r.center().y()
        t = time.monotonic()
        amber = self.state in ("command", "command_locked")
        base = QColor("#ffa946") if amber else QColor(255, 255, 255)
        active = self.level > 0.02
        if not active:
            base.setAlpha(102)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(base)
        for i in range(bars):
            wave = 0.45 + 0.55 * abs(math.sin(t * 6.3 + i * 0.85))
            amp = min(1.0, self.level * 5 * wave) if active else 0.0
            bh = 2 + amp * 16
            p.drawRoundedRect(QRectF(x0 + i * (bw + gap), cy - bh / 2, bw, bh), 1, 1)

    def _paint_buttons(self, p):
        cancel, stop = self._button_rects()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.SAND[950]))
        p.drawEllipse(cancel)
        pen = QPen(QColor(theme.SAND[50]), 1.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        c = cancel.center()
        p.drawLine(QPointF(c.x() - 3.5, c.y() - 3.5), QPointF(c.x() + 3.5, c.y() + 3.5))
        p.drawLine(QPointF(c.x() + 3.5, c.y() - 3.5), QPointF(c.x() - 3.5, c.y() + 3.5))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.SAND[50]))
        p.drawEllipse(stop)
        p.setBrush(QColor(theme.VAST[950]))
        s = stop.center()
        p.drawRoundedRect(QRectF(s.x() - 3.5, s.y() - 3.5, 7, 7), 1.5, 1.5)

    def _paint_spinner(self, p, c):
        t = time.monotonic()
        step = int((t % 1.1) / 1.1 * 8)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(8):
            alpha = 0.15 + 0.73 * (((i - step) % 8) / 7)
            col = QColor(163, 148, 199)
            col.setAlphaF(alpha)
            p.save()
            p.translate(c)
            p.rotate(i * 45)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(-1, -8, 2, 5), 1, 1)
            p.restore()

    def _paint_tooltip(self, p):
        f = theme.ui_font(14, QFont.Weight.Normal)
        fb = theme.ui_font(14, QFont.Weight.Bold)
        parts = [("Hold ", f), (self.shortcut_text, fb), (" to dictate", f)]
        width = sum(QFontMetrics(font).horizontalAdvance(text) for text, font in parts) + 28
        r = QRectF((W - width) / 2, self._pill_rect().top() - 42, width, 32)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#000000"))
        p.drawRoundedRect(r, 16, 16)
        x = r.left() + 14
        for text, font in parts:
            p.setFont(font)
            p.setPen(QColor("#ffffff") if font is fb else QColor(theme.SAND[600]))
            p.drawText(QRectF(x, r.top(), 400, r.height()), Qt.AlignmentFlag.AlignVCenter, text)
            x += QFontMetrics(font).horizontalAdvance(text)

    def _paint_notice(self, p):
        n = self.notice
        title_f = theme.ui_font(15, QFont.Weight.DemiBold)
        sub_f = theme.ui_font(13)
        fm, fs = QFontMetrics(title_f), QFontMetrics(sub_f)
        max_w = 440 - 32
        title_w = min(max_w, fm.horizontalAdvance(n["title"]))
        sub_lines = fs.boundingRect(0, 0, max_w, 200, Qt.TextFlag.TextWordWrap, n["subtitle"]) if n["subtitle"] else None
        width = max(title_w, sub_lines.width() if sub_lines else 0) + 32
        height = 20 + 24 + (sub_lines.height() + 4 if sub_lines else 0)
        age = time.monotonic() - n["born"]
        rise = min(1.0, age / 0.25)
        fade = min(1.0, max(0.0, (n["until"] - time.monotonic()) / 0.25))
        p.setOpacity(min(rise, fade))
        bottom = self._pill_rect().top() - 10 if self.size[1] > 1 else H - BOTTOM_GAP
        r = QRectF((W - width) / 2, bottom - height - (1 - rise) * 8, width, height)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#000000"))
        p.drawRoundedRect(r, 20, 20)
        p.setFont(title_f)
        p.setPen(QColor(theme.SAND[50]))
        p.drawText(QRectF(r.left() + 16, r.top() + 10, max_w, 24), Qt.AlignmentFlag.AlignVCenter,
                   fm.elidedText(n["title"], Qt.TextElideMode.ElideRight, max_w))
        if sub_lines:
            p.setFont(sub_f)
            p.setPen(QColor(theme.VAST[300]))
            p.drawText(QRectF(r.left() + 16, r.top() + 36, max_w, sub_lines.height() + 2),
                       Qt.TextFlag.TextWordWrap, n["subtitle"])
        p.setOpacity(1.0)
