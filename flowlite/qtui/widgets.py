"""Shared Qt components styled after Wispr Flow's hub (measured tokens in theme.py).

Pages build on these so the whole app looks consistent:
Toggle, Card, ListCard, TabBar, KeyChips, Hero, IconButton, PageHeader, SettingsGroup,
SettingRow, Modal, confirm(), Toast, EmptyState, section_label().
"""

import math

from PySide6.QtCore import (Property, QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF,
                            QSize, Qt, QTimer, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)
from PySide6.QtWidgets import (QAbstractButton, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QSizePolicy, QToolButton, QVBoxLayout, QWidget)

from . import icons, theme


# ----------------------------------------------------------------------------- basics
def label(text="", px=15, weight=QFont.Weight.Normal, color=theme.FOREGROUND, wrap=False, object_name=None):
    lb = QLabel(text)
    lb.setFont(theme.ui_font(px, weight))
    lb.setStyleSheet(f"color: {color}; background: transparent;")
    lb.setWordWrap(wrap)
    if object_name:
        lb.setObjectName(object_name)
    return lb


def display_label(text, px=40, color=theme.FOREGROUND):
    """Serif display text (EB Garamond); supports <i>…</i> for the italic accent words."""
    lb = QLabel(text)
    lb.setTextFormat(Qt.TextFormat.RichText)
    f = theme.display_font(px)
    f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 96)
    lb.setFont(f)
    # the app-wide "* { font-family }" rule would otherwise replace the serif
    lb.setStyleSheet(f'color: {color}; background: transparent; font-family: "{theme.DISPLAY_FAMILY}";'
                     f" font-size: {px}px;")
    return lb


def section_label(text):
    lb = label(text.upper(), 12, QFont.Weight.DemiBold, theme.SAND[950])
    f = lb.font()
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
    lb.setFont(f)
    return lb


def button(text, kind="Primary", on_click=None):
    b = QPushButton(text)
    b.setObjectName(kind)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        b.clicked.connect(on_click)
    return b


def shadow(widget, blur=40, dy=12, alpha=40):
    eff = QGraphicsDropShadowEffect(widget)
    eff.setBlurRadius(blur)
    eff.setOffset(0, dy)
    eff.setColor(QColor(26, 26, 26, alpha))
    widget.setGraphicsEffect(eff)
    return eff


def hline():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {theme.SECONDARY}; border: none;")
    return line


# ----------------------------------------------------------------------------- toggle
class Toggle(QAbstractButton):
    """Wispr's switch: 52x30 track, near-black when on, sand when off, white knob."""

    def __init__(self, checked=False, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(52, 30)
        self._pos = 1.0 if checked else 0.0
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def get_knob(self):
        return self._pos

    def set_knob(self, v):
        self._pos = v
        self.update()

    knob = Property(float, get_knob, set_knob)

    def sizeHint(self):
        return QSize(52, 30)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        off, on = QColor(theme.SAND[700]), QColor(theme.VAST[950])
        c = QColor(
            int(off.red() + (on.red() - off.red()) * self._pos),
            int(off.green() + (on.green() - off.green()) * self._pos),
            int(off.blue() + (on.blue() - off.blue()) * self._pos))
        if not self.isEnabled():
            c.setAlpha(110)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(QRectF(0, 0, 52, 30), 15, 15)
        x = 3 + self._pos * 22
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, 3, 24, 24))


# ----------------------------------------------------------------------------- containers
class Card(QFrame):
    def __init__(self, bg=theme.CARD, radius=12, border=theme.SECONDARY, padding=20, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.setStyleSheet(
            f"#Card {{ background: {bg}; border: 1px solid {border}; border-radius: {radius}px; }}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(padding, padding, padding, padding)
        self.lay.setSpacing(10)


class ListCard(QFrame):
    """Rounded white list with hairline separators (History, Dictionary, Snippets rows)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ListCard")
        self.setStyleSheet(f"#ListCard {{ background: {theme.LIST_BG}; border: 1px solid {theme.SECONDARY};"
                           f" border-radius: 12px; }}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.rows = []

    def clear(self):
        for w in self.rows:
            w.setParent(None)
            w.deleteLater()
        self.rows = []
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def add(self, row):
        if self.rows:
            sep = hline()
            self.lay.addWidget(sep)
            self.rows.append(sep)
        self.lay.addWidget(row)
        self.rows.append(row)


class HoverRow(QFrame):
    """List row that tints on hover and reveals `actions` (a widget) on the right."""

    clicked = Signal()

    def __init__(self, parent=None, min_height=64):
        super().__init__(parent)
        self.setObjectName("HoverRow")
        self.setMinimumHeight(min_height)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._base = "#HoverRow { background: transparent; border: none; }"
        self._hover = f"#HoverRow {{ background: {theme.SAND[200]}; border: none; }}"
        self.setStyleSheet(self._base)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(20, 12, 16, 12)
        self.lay.setSpacing(16)
        self.actions = None

    def set_actions(self, widget):
        self.actions = widget
        widget.setVisible(False)
        self.lay.addWidget(widget, 0, Qt.AlignmentFlag.AlignVCenter)

    def enterEvent(self, e):
        self.setStyleSheet(self._hover)
        if self.actions:
            self.actions.setVisible(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.setStyleSheet(self._base)
        if self.actions:
            self.actions.setVisible(False)
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(e)


# ----------------------------------------------------------------------------- tabs
class TabBar(QWidget):
    """Underline tabs ("All · Personal · Learned"), optional right-side tools and a Beta tag."""

    changed = Signal(int)

    def __init__(self, tabs, parent=None, badges=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.buttons = []
        for i, name in enumerate(tabs):
            b = QPushButton(name)
            b.setObjectName("Tab")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _=False, idx=i: self.select(idx))
            lay.addWidget(b)
            if badges and name in badges:
                b.setStyleSheet("margin-right: 12px;")
                tag = label(badges[name], 12, QFont.Weight.Medium, "#9b6fc4")
                tag.setStyleSheet("color: #9b6fc4; background: #f6eefc; border-radius: 6px; padding: 2px 8px;")
                tag.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
                lay.addWidget(tag, 0, Qt.AlignmentFlag.AlignVCenter)
                lay.addSpacing(18)
            self.buttons.append(b)
        lay.addStretch(1)
        self.tools = QHBoxLayout()
        self.tools.setSpacing(6)
        lay.addLayout(self.tools)
        self.index = -1
        self.select(0, emit=False)

    def add_tool(self, widget):
        self.tools.addWidget(widget)

    def select(self, idx, emit=True):
        for i, b in enumerate(self.buttons):
            b.setChecked(i == idx)
        if idx != self.index:
            self.index = idx
            if emit:
                self.changed.emit(idx)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setPen(QPen(QColor(theme.SECONDARY), 1))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)


# ----------------------------------------------------------------------------- keys
KEY_LABELS = {"ctrl": "Ctrl", "win": "Win", "alt": "Alt", "shift": "Shift", "space": "Space", "esc": "Esc",
              "enter": "Enter", "tab": "Tab", "backspace": "Backspace"}


def key_label(key):
    return KEY_LABELS.get(key, key.upper() if len(key) == 1 else key.capitalize())


class KeyChips(QWidget):
    """Keycaps for a shortcut string like "win+alt+1"."""

    def __init__(self, shortcut, parent=None, px=13, dark=False):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        bg, fg, border = (("#ffffeb", "#1a1a1a", "#646464") if dark else
                          ("#ffffff", theme.FOREGROUND, theme.SECONDARY))
        for key in [k for k in shortcut.split("+") if k]:
            chip = QLabel(key_label(key))
            chip.setFont(theme.ui_font(px, QFont.Weight.Medium))
            chip.setStyleSheet(f"background: {bg}; color: {fg}; border: 1px solid {border};"
                               f" border-radius: 6px; padding: 2px 7px;")
            lay.addWidget(chip)


# ----------------------------------------------------------------------------- hero
HERO_PALETTES = {
    "dusk": [("#2b3a40", 0.0), ("#5a4a3a", 0.55), ("#3a2a22", 1.0)],
    "ember": [("#4a2c25", 0.0), ("#7a5a3a", 0.5), ("#35251f", 1.0)],
    "lagoon": [("#1f3a46", 0.0), ("#3c5a5c", 0.5), ("#2a2f33", 1.0)],
    "plum": [("#2d2433", 0.0), ("#5a4352", 0.55), ("#24202a", 1.0)],
}


class Hero(QFrame):
    """Banner card with a soft painted gradient, a serif headline, body text and buttons.

    Original artwork (painted gradients and blurred light blobs); Wispr uses photos here.
    """

    dismissed = Signal()

    def __init__(self, title_html, body, palette="dusk", closable=True, parent=None, height=None):
        super().__init__(parent)
        self.palette = HERO_PALETTES[palette]
        self.setMinimumHeight(height or 220)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 34, 40, 34)
        lay.setSpacing(10)
        self.title = display_label(title_html, 40, "#fcfcfb")
        lay.addWidget(self.title)
        self.body = label(body, 16, QFont.Weight.Normal, "#f4f2ec", wrap=True)
        self.body.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(self.body)
        self.extra = QVBoxLayout()
        self.extra.setSpacing(10)
        lay.addLayout(self.extra)
        self.buttons = QHBoxLayout()
        self.buttons.setSpacing(10)
        lay.addSpacing(8)
        lay.addLayout(self.buttons)
        self.buttons.addStretch(1)
        lay.addStretch(1)
        if closable:
            self.close_btn = QToolButton(self)
            self.close_btn.setIcon(icons.icon("close", 14, "#ffffff", 2.2))
            self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.close_btn.setStyleSheet("QToolButton { background: rgba(255,255,255,0.22); border: none;"
                                         " border-radius: 14px; } QToolButton:hover { background: rgba(255,255,255,0.36); }")
            self.close_btn.setFixedSize(28, 28)
            self.close_btn.clicked.connect(self._dismiss)

    def add_button(self, text, on_click=None, light=True):
        b = QPushButton(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFont(theme.ui_font(16, QFont.Weight.Medium))
        if light:
            b.setStyleSheet("QPushButton { background: #f4f1ea; color: #1a1a1a; border: none; border-radius: 8px;"
                            " padding: 10px 20px; } QPushButton:hover { background: #ffffff; }")
        else:
            b.setStyleSheet("QPushButton { background: transparent; color: #ffffff; border: none; padding: 10px 8px; }"
                            " QPushButton:hover { text-decoration: underline; }")
        if on_click:
            b.clicked.connect(on_click)
        self.buttons.insertWidget(self.buttons.count() - 1, b)
        return b

    def add_chip(self, text, on_click=None, italic=False, parent_layout=None):
        chip = QPushButton(text)
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        f = theme.ui_font(16, QFont.Weight.Medium)
        f.setItalic(italic)
        chip.setFont(f)
        chip.setStyleSheet("QPushButton { background: rgba(255,255,255,0.45); color: #2a2a2a; border: none;"
                           " border-radius: 8px; padding: 9px 18px; } QPushButton:hover { background: rgba(255,255,255,0.6); }")
        if on_click:
            chip.clicked.connect(on_click)
        (parent_layout or self.buttons).insertWidget((parent_layout or self.buttons).count() - 1, chip)
        return chip

    def _dismiss(self):
        self.hide()
        self.dismissed.emit()

    def resizeEvent(self, e):
        if hasattr(self, "close_btn"):
            self.close_btn.move(self.width() - 50, 22)
        super().resizeEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, 16, 16)
        p.setClipPath(path)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        for color, stop in self.palette:
            g.setColorAt(stop, QColor(color))
        p.fillRect(r, g)
        # soft out-of-focus light blobs
        for cx, cy, rad, color, a in ((0.78, 0.25, 0.45, "#d9b98a", 70), (0.15, 0.85, 0.4, "#7aa0a8", 55),
                                       (0.55, 0.65, 0.3, "#e8d2b5", 45)):
            rg = QRadialGradient(QPointF(r.width() * cx, r.height() * cy), r.width() * rad)
            c = QColor(color)
            c.setAlpha(a)
            rg.setColorAt(0, c)
            c2 = QColor(color)
            c2.setAlpha(0)
            rg.setColorAt(1, c2)
            p.fillRect(r, rg)
        shade = QLinearGradient(r.topLeft(), r.topRight())
        shade.setColorAt(0, QColor(0, 0, 0, 90))
        shade.setColorAt(0.7, QColor(0, 0, 0, 10))
        p.fillRect(r, shade)


# ----------------------------------------------------------------------------- buttons/headers
class IconButton(QToolButton):
    def __init__(self, name, tooltip="", size=18, box=34, color=theme.FOREGROUND, parent=None):
        super().__init__(parent)
        self.setIcon(icons.icon(name, size, color))
        self.setIconSize(QSize(size, size))
        self.setFixedSize(box, box)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(f"QToolButton {{ background: transparent; border: none; border-radius: 8px; }}"
                           f" QToolButton:hover {{ background: {theme.SECONDARY}; }}"
                           f" QToolButton:checked {{ background: {theme.SECONDARY}; }}")


class PageHeader(QWidget):
    def __init__(self, title, parent=None, beta=False):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        self.title = label(title, 26, QFont.Weight.DemiBold)
        lay.addWidget(self.title)
        if beta:
            tag = QLabel("Beta")
            tag.setFont(theme.ui_font(13, QFont.Weight.DemiBold))
            tag.setStyleSheet("background: #1a1a1a; color: #fcfcfb; border-radius: 5px; padding: 3px 8px;")
            lay.addWidget(tag)
        lay.addStretch(1)
        self.right = QHBoxLayout()
        self.right.setSpacing(12)
        lay.addLayout(self.right)

    def add_right(self, widget):
        self.right.addWidget(widget)
        return widget


class SearchField(QLineEdit):
    def __init__(self, placeholder="Search", parent=None):
        super().__init__(parent)
        self.setPlaceholderText(placeholder)
        self.addAction(icons.icon("search", 16, theme.FOREGROUND_TERTIARY), QLineEdit.ActionPosition.LeadingPosition)
        self.setClearButtonEnabled(True)


class EmptyState(QWidget):
    def __init__(self, icon_name, title, body="", parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 40, 20, 40)
        lay.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, 28, theme.FOREGROUND_TERTIARY))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ic)
        t = label(title, 20, QFont.Weight.Medium, theme.SAND[950])
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        if body:
            b = label(body, 15, color=theme.FOREGROUND_TERTIARY, wrap=True)
            b.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(b)


# ----------------------------------------------------------------------------- settings rows
class SettingsGroup(QFrame):
    """Rounded sand card holding SettingRows separated by hairlines (Settings panes)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SettingsGroup")
        self.setStyleSheet(f"#SettingsGroup {{ background: {theme.TERTIARY}; border-radius: 12px; }}")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(24, 6, 24, 6)
        self.lay.setSpacing(0)
        self._count = 0

    def add(self, row):
        if self._count:
            sep = QFrame()
            sep.setFixedHeight(1)
            sep.setStyleSheet(f"background: {theme.SECONDARY};")
            self.lay.addWidget(sep)
        self.lay.addWidget(row)
        self._count += 1
        return row


class SettingRow(QWidget):
    def __init__(self, title, description="", control=None, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 18, 0, 18)
        lay.setSpacing(16)
        text = QVBoxLayout()
        text.setSpacing(4)
        self.title = label(title, 16, QFont.Weight.Medium)
        text.addWidget(self.title)
        self.description = label(description, 15, color=theme.SAND[950], wrap=True)
        self.description.setTextFormat(Qt.TextFormat.RichText)
        self.description.setVisible(bool(description))
        text.addWidget(self.description)
        lay.addLayout(text, 1)
        if control is not None:
            lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self.control = control

    def set_description(self, html):
        self.description.setText(html)
        self.description.setVisible(bool(html))


def change_button(on_click=None, text="Change"):
    b = QPushButton(text)
    b.setObjectName("Secondary")
    b.setMinimumWidth(200)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        b.clicked.connect(on_click)
    return b


# ----------------------------------------------------------------------------- modal
class Modal(QWidget):
    """Dims the host window and shows a centered rounded card (Settings, dialogs).

    Usage: m = Modal(host_window, width, height); m.body.addWidget(...); m.open()
    """

    closed = Signal()

    def __init__(self, host, width=560, height=None, radius=12, padding=28):
        super().__init__(host)
        self.host = host
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setObjectName("ModalScrim")
        self.setStyleSheet("#ModalScrim { background: rgba(26, 26, 26, 0.32); }")
        self.card = QFrame(self)
        self.card.setObjectName("ModalCard")
        self.card.setStyleSheet(f"#ModalCard {{ background: {theme.CARD}; border-radius: {radius}px; }}")
        shadow(self.card, 60, 20, 60)
        self.card.setFixedWidth(width)
        if height:
            self.card.setFixedHeight(height)
        self.body = QVBoxLayout(self.card)
        self.body.setContentsMargins(padding, padding, padding, padding)
        self.body.setSpacing(14)
        self.hide()
        host.installEventFilter(self)

    def eventFilter(self, obj, ev):
        if obj is self.host and ev.type() == ev.Type.Resize and self.isVisible():
            self._place()
        return False

    def _place(self):
        self.setGeometry(self.host.rect())
        self.card.adjustSize()
        self.card.move((self.width() - self.card.width()) // 2, (self.height() - self.card.height()) // 2)

    def open(self):
        self._place()
        self.show()
        self.raise_()
        self.setFocus()

    def close_modal(self):
        self.hide()
        self.closed.emit()
        self.deleteLater()

    def mousePressEvent(self, e):
        if not self.card.geometry().contains(e.position().toPoint()):
            self.close_modal()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.close_modal()
        else:
            super().keyPressEvent(e)


def confirm(host, title, body, confirm_text="Confirm", on_confirm=None, danger=False):
    m = Modal(host, 460)
    m.body.addWidget(label(title, 20, QFont.Weight.DemiBold))
    m.body.addWidget(label(body, 15, color=theme.SAND[950], wrap=True))
    row = QHBoxLayout()
    row.addStretch(1)
    row.addWidget(button("Cancel", "Secondary", m.close_modal))
    ok = button(confirm_text, "Primary")
    if danger:
        ok.setStyleSheet(f"background: {theme.DANGER}; color: white; border-radius: 8px; padding: 10px 20px;")

    def go():
        m.close_modal()
        if on_confirm:
            on_confirm()
    ok.clicked.connect(go)
    row.addWidget(ok)
    m.body.addLayout(row)
    m.open()
    return m


# ----------------------------------------------------------------------------- toast
class Toast(QLabel):
    """Small black pill at the bottom of the hub ("Shortcut saved", "Copied")."""

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.setFont(theme.ui_font(14, QFont.Weight.Medium))
        self.setStyleSheet("background: #1a1a1a; color: #fcfcfb; border-radius: 18px; padding: 9px 18px;")
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_text(self, text, ms=2200):
        self.setText(text)
        self.adjustSize()
        self.move((self.host.width() - self.width()) // 2, self.host.height() - self.height() - 28)
        self.show()
        self.raise_()
        self._timer.start(ms)
