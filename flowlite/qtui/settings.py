"""Settings modal (General, System, Models, Experimental, Data and Privacy) and its dialogs.

Layout follows Wispr Flow's settings sheet: a 960x640 card over the dimmed hub with a sand
rail on the left (section labels + icon items) and a serif pane title on the right above
rounded sand groups of rows. Every change is saved immediately with ctx.save_settings().

Dialogs: ShortcutsDialog (key-capture fields with validation), MicrophoneDialog (input
devices + live level), LanguagesDialog (Whisper languages with native names).
"""

import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRectF, QSize, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QStandardItemModel
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QScrollArea,
                               QSizePolicy,
                               QToolButton, QVBoxLayout, QWidget)

from .. import store
from . import icons, theme, widgets

icons.PATHS.setdefault(
    "zap", '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 '
           '.78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>')
icons.PATHS.setdefault(
    "folder", '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 '
              '0 0-2 2v13a2 2 0 0 0 2 2Z"/>')

VERSION_TEXT = "FlowLite v2.0 · offline"
CAPTURE_BORDER = "#A88ED5"
ERROR_RED = "#dc2626"

# ----------------------------------------------------------------------------- languages
# Whisper language code -> (English name, native name)
LANGUAGES = {
    "en": ("English", "English"),
    "he": ("Hebrew", "עברית"),
    "ru": ("Russian", "Русский"),
    "es": ("Spanish", "Español"),
    "fr": ("French", "Français"),
    "de": ("German", "Deutsch"),
    "it": ("Italian", "Italiano"),
    "pt": ("Portuguese", "Português"),
    "nl": ("Dutch", "Nederlands"),
    "pl": ("Polish", "Polski"),
    "uk": ("Ukrainian", "Українська"),
    "ar": ("Arabic", "العربية"),
    "fa": ("Persian", "فارسی"),
    "tr": ("Turkish", "Türkçe"),
    "hi": ("Hindi", "हिन्दी"),
    "bn": ("Bengali", "বাংলা"),
    "ur": ("Urdu", "اردو"),
    "zh": ("Chinese", "中文"),
    "ja": ("Japanese", "日本語"),
    "ko": ("Korean", "한국어"),
    "vi": ("Vietnamese", "Tiếng Việt"),
    "th": ("Thai", "ไทย"),
    "id": ("Indonesian", "Bahasa Indonesia"),
    "ms": ("Malay", "Bahasa Melayu"),
    "tl": ("Tagalog", "Tagalog"),
    "sv": ("Swedish", "Svenska"),
    "no": ("Norwegian", "Norsk"),
    "da": ("Danish", "Dansk"),
    "fi": ("Finnish", "Suomi"),
    "cs": ("Czech", "Čeština"),
    "sk": ("Slovak", "Slovenčina"),
    "hu": ("Hungarian", "Magyar"),
    "ro": ("Romanian", "Română"),
    "bg": ("Bulgarian", "Български"),
    "el": ("Greek", "Ελληνικά"),
    "sr": ("Serbian", "Српски"),
    "hr": ("Croatian", "Hrvatski"),
    "sl": ("Slovenian", "Slovenščina"),
    "ca": ("Catalan", "Català"),
    "lt": ("Lithuanian", "Lietuvių"),
    "lv": ("Latvian", "Latviešu"),
    "et": ("Estonian", "Eesti"),
    "ta": ("Tamil", "தமிழ்"),
    "te": ("Telugu", "తెలుగు"),
    "sw": ("Swahili", "Kiswahili"),
    "af": ("Afrikaans", "Afrikaans"),
    "yi": ("Yiddish", "ייִדיש"),
    "ka": ("Georgian", "ქართული"),
    "hy": ("Armenian", "Հայերեն"),
    "az": ("Azerbaijani", "Azərbaycan"),
    "kk": ("Kazakh", "Қазақ"),
}


def language_label(code):
    """"Hebrew (עברית)"; just "English" when the native name is the same."""
    english, native = LANGUAGES.get(code, (code, code))
    return english if native == english else f"{english} ({native})"


def languages_summary(settings):
    if settings.auto_detect_all:
        return "Auto-detect (99 languages)"
    return " · ".join(language_label(c) for c in settings.languages) or "None selected"


# ----------------------------------------------------------------------------- shortcuts
SHORTCUT_ACTIONS = [  # settings key, label, hint
    ("push_to_talk", "Push to talk", "Hold to dictate"),
    ("hands_free", "Hands-free mode", "or double-tap push to talk"),
    ("command_mode", "Command mode", "Hold and say what to change"),
    ("paste_last", "Paste last transcript", ""),
    ("copy_last", "Copy last transcript", ""),
    ("transform_1", "Transform 1", ""),
    ("transform_2", "Transform 2", ""),
    ("dismiss", "Cancel", "Stops a dictation"),
]
ACTION_LABELS = {k: lbl for k, lbl, _ in SHORTCUT_ACTIONS}
MODIFIERS = ("ctrl", "win", "alt", "shift")

# Windows virtual-key codes -> flowlite.hotkeys key names (kept in sync with hotkeys.VK_NAMES)
VK_NAMES = {
    0x10: "shift", 0xA0: "shift", 0xA1: "shift",
    0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
    0x12: "alt", 0xA4: "alt", 0xA5: "alt",
    0x5B: "win", 0x5C: "win",
    0x20: "space", 0x1B: "esc", 0x0D: "enter", 0x09: "tab", 0x08: "backspace",
}
VK_NAMES.update({vk: f"f{vk - 0x6F}" for vk in range(0x70, 0x88)})
VK_NAMES.update({vk: chr(vk).lower() for vk in range(0x41, 0x5B)})
VK_NAMES.update({vk: chr(vk) for vk in range(0x30, 0x3A)})

QT_NAMES = {
    Qt.Key.Key_Control: "ctrl", Qt.Key.Key_Meta: "win", Qt.Key.Key_Super_L: "win", Qt.Key.Key_Super_R: "win",
    Qt.Key.Key_Alt: "alt", Qt.Key.Key_AltGr: "alt", Qt.Key.Key_Shift: "shift", Qt.Key.Key_Space: "space",
    Qt.Key.Key_Escape: "esc", Qt.Key.Key_Return: "enter", Qt.Key.Key_Enter: "enter", Qt.Key.Key_Tab: "tab",
    Qt.Key.Key_Backtab: "tab", Qt.Key.Key_Backspace: "backspace",
}
QT_NAMES.update({Qt.Key(Qt.Key.Key_F1.value + i): f"f{i + 1}" for i in range(24)})
QT_NAMES.update({Qt.Key(Qt.Key.Key_A.value + i): chr(ord("a") + i) for i in range(26)})
QT_NAMES.update({Qt.Key(Qt.Key.Key_0.value + i): str(i) for i in range(10)})

RESERVED = {frozenset(s.split("+")) for s in (
    "ctrl+c", "ctrl+v", "ctrl+x", "ctrl+z", "ctrl+y", "ctrl+a", "ctrl+s", "alt+tab", "alt+f4", "alt+esc",
    "ctrl+esc", "ctrl+shift+esc", "ctrl+alt+delete", "win+l", "win+d", "win+e", "win+r", "win+tab")}


def event_key_name(e):
    """hotkeys.py name of the key in a QKeyEvent (None when the key can't be used)."""
    vk = e.nativeVirtualKey()
    if vk and vk in VK_NAMES:
        return VK_NAMES[vk]
    try:
        return QT_NAMES.get(Qt.Key(e.key()))
    except ValueError:
        return None


def chord_string(keys):
    mods = [m for m in MODIFIERS if m in keys]
    rest = sorted(k for k in keys if k not in MODIFIERS)
    return "+".join(mods + rest)


def chord_keys(shortcut):
    return frozenset(k for k in (shortcut or "").lower().split("+") if k)


def validate_chord(keys, action, shortcuts):
    """Error text for an unusable chord, else None."""
    keys = frozenset(keys)
    mods = [k for k in keys if k in MODIFIERS]
    others = [k for k in keys if k not in MODIFIERS]
    if len(keys) > 3:
        return "Use up to 3 keys."
    if len(others) > 1:
        return "Use modifier keys plus at most one other key."
    if not mods:
        key = others[0] if others else ""
        if not (key == "esc" or (key.startswith("f") and key[1:].isdigit())):
            return "Add Ctrl, Win, Alt or Shift to this key."
    if not others and len(mods) == 1:
        return "A single modifier would fire all the time. Add another key."
    if mods == ["shift"] and others and others[0] not in ("esc", "space") and not others[0].startswith("f"):
        return "Shift plus a letter or digit would block normal typing."
    if keys in RESERVED:
        return f"{' + '.join(widgets.key_label(k) for k in chord_string(keys).split('+'))} is reserved by Windows."
    for other, value in shortcuts.items():
        if other != action and chord_keys(value) == keys:
            return f"Already used for {ACTION_LABELS.get(other, other)}."
    return None


def default_shortcuts():
    return store.Settings.__dataclass_fields__["shortcuts"].default_factory()


# ----------------------------------------------------------------------------- helpers
class _Bridge(QObject):
    """Runs fn() on a worker thread and delivers cb(result, error) on the GUI thread."""

    done = Signal(object, object)

    def __init__(self, parent, fn, cb):
        super().__init__(parent)
        self._cb = cb
        self.done.connect(self._deliver)
        threading.Thread(target=self._work, args=(fn,), daemon=True).start()

    def _work(self, fn):
        try:
            res, err = fn(), None
        except Exception as e:  # noqa: BLE001 - surfaced to the UI
            res, err = None, e
        try:
            self.done.emit(res, err)
        except RuntimeError:
            pass  # owner went away

    @Slot(object, object)
    def _deliver(self, res, err):
        try:
            self._cb(res, err)
        except RuntimeError:
            pass  # widgets deleted meanwhile
        self.deleteLater()


def run_async(owner, fn, cb):
    return _Bridge(owner, fn, cb)


def _thin_scrollbar(scroll):
    scroll.verticalScrollBar().setStyleSheet(
        f"QScrollBar:vertical {{ background: transparent; border: none; width: 8px; margin: 6px 2px; }}"
        f" QScrollBar::handle:vertical {{ background: {theme.SAND[700]}; border-radius: 2px; min-height: 40px; }}"
        f" QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; border: none; }}"
        f" QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}")


def _fixed_width(w, px):
    w.setMinimumWidth(px)
    w.setFixedWidth(px)
    return w


def _combo(items, current=None, width=164):
    cb = Combo()
    cb.setCursor(Qt.CursorShape.PointingHandCursor)
    for value, text in items:
        cb.addItem(text, value)
    if current is not None:
        idx = cb.findData(current)
        if idx >= 0:
            cb.setCurrentIndex(idx)
    _fixed_width(cb, width)
    cb.fixed = width
    cb.view().setMinimumWidth(max(width, cb.view().sizeHintForColumn(0) + 32))
    return cb


def _change(on_click=None, text="Change", color=theme.FOREGROUND, width=164):
    """widgets.change_button with its fill pinned on the button itself (ancestor sheets can't drop it)."""
    b = widgets.change_button(on_click, text)
    b.setStyleSheet(f"QPushButton {{ background: {theme.SECONDARY}; color: {color}; border: none; border-radius: 8px;"
                    f" padding: 9px 22px; font-size: 15px; font-weight: 500; }}"
                    f" QPushButton:hover {{ background: {theme.SAND[700]}; }}"
                    f" QPushButton:disabled {{ color: {theme.FOREGROUND_TERTIARY}; }}")
    return _fixed_width(b, width)


def _danger_button(text, on_click):
    return _change(on_click, text, ERROR_RED)


class Combo(QComboBox):
    """Combobox with a painted Lucide chevron (the app sheet hides the native arrow)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"QComboBox {{ background: {theme.CARD}; border: 1px solid {theme.SECONDARY};"
                           f" border-radius: 8px; padding: 8px 30px 8px 14px; font-size: 15px; min-width: 0; }}"
                           f" QComboBox:hover {{ border-color: {theme.SAND[700]}; }}"
                           f" QComboBox::drop-down {{ border: none; width: 28px; }}"
                           f" QComboBox::down-arrow {{ image: none; width: 0; height: 0; }}"
                           f" QComboBox QAbstractItemView {{ background: {theme.CARD}; border: 1px solid {theme.SECONDARY};"
                           f" padding: 4px; outline: none; selection-background-color: {theme.SECONDARY};"
                           f" selection-color: {theme.FOREGROUND}; }}")

    fixed = 0

    def event(self, e):
        res = super().event(e)
        if e.type() == QEvent.Type.Polish and self.fixed:
            self.setFixedWidth(self.fixed)  # style sheet min-width is applied at polish time
        return res

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        pm = icons.pixmap("chevron", 14, theme.FOREGROUND if self.isEnabled() else theme.SAND[700], 2)
        p.drawPixmap(self.width() - 30, (self.height() - 14) // 2, pm)


def _title(text):
    return widgets.label(text, 20, QFont.Weight.DemiBold)


def _muted(text, px=14, wrap=True):
    return widgets.label(text, px, color=theme.FOREGROUND_TERTIARY, wrap=wrap)


def _error_label():
    lb = widgets.label("", 13, color=ERROR_RED, wrap=True)
    lb.hide()
    return lb


def _clear_layout(lay):
    while lay.count():
        item = lay.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear_layout(item.layout())


def mic_display_name(settings):
    mic = settings.mic or ""
    if not mic:
        return "Default microphone"
    if mic.isdigit():
        try:
            import sounddevice as sd
            return _full_name(sd.query_devices(int(mic))["name"], sd.query_devices())
        except Exception:  # noqa: BLE001
            return f"Device {mic}"
    return mic


def _full_name(name, devices):
    """MME truncates names to 31 characters; borrow the full name another host API reports."""
    longer = [d["name"] for d in devices if d["max_input_channels"] > 0 and d["name"].startswith(name.rstrip())]
    return max(longer, key=len).strip() if longer else name.strip()


def input_devices():
    """[(index, name)] for the default input's host API (deduplicated), plus the default input's name."""
    import sounddevice as sd
    devices = sd.query_devices()
    try:
        default = sd.query_devices(kind="input")
        hostapi, default_name = default["hostapi"], _full_name(default["name"], devices)
    except Exception:  # noqa: BLE001 - no default input
        hostapi, default_name = None, ""
    out, seen = [], set()
    for i, d in enumerate(devices):
        if d["max_input_channels"] <= 0 or (hostapi is not None and d["hostapi"] != hostapi):
            continue
        name = d["name"]
        if name in seen or any(s in name for s in ("Sound Mapper", "Primary Sound Capture", "Stereo Mix")):
            continue
        seen.add(name)
        out.append((i, _full_name(name, devices)))
    return out, default_name


HF_REPOS = {"large-v3-turbo": "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo"}
SPEECH_MODELS = [  # name, label
    ("tiny", "Tiny · fastest"),
    ("base", "Base"),
    ("base.en", "Base · English only"),
    ("small", "Small · recommended"),
    ("small.en", "Small · English only"),
    ("medium", "Medium"),
    ("large-v3-turbo", "Large v3 Turbo"),
]


def hf_hub_dir():
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    home = Path(os.environ.get("HF_HOME") or (Path.home() / ".cache" / "huggingface"))
    return home / "hub"


def whisper_downloaded(name):
    repo = HF_REPOS.get(name, f"models--Systran--faster-whisper-{name}")
    snap = hf_hub_dir() / repo / "snapshots"
    try:
        return snap.is_dir() and any(snap.iterdir())
    except OSError:
        return False


# ----------------------------------------------------------------------------- small widgets
class ElidedLabel(QLabel):
    """One-line label that elides with "…" instead of widening its parent (long device names)."""

    def __init__(self, text, px=15, color=theme.FOREGROUND):
        super().__init__()
        self.full = text
        self.setFont(theme.ui_font(px))
        self.setStyleSheet(f"color: {color}; background: transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(40)
        self.setToolTip(text)
        self.setText(text)

    def resizeEvent(self, e):
        self.setText(self.fontMetrics().elidedText(self.full, Qt.TextElideMode.ElideRight, self.width()))
        super().resizeEvent(e)


class CheckRow(QFrame):
    """Clickable list row with a check box (or radio dot) on the right."""

    clicked = Signal()

    def __init__(self, text, checked=False, radio=False, sub="", parent=None):
        super().__init__(parent)
        self.setObjectName("CheckRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(46)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._radio = radio
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(12)
        col = QVBoxLayout()
        col.setSpacing(1)
        col.addWidget(ElidedLabel(text, 15, theme.FOREGROUND))
        if sub:
            col.addWidget(ElidedLabel(sub, 13, theme.FOREGROUND_TERTIARY))
        lay.addLayout(col, 1)
        self.box = QLabel()
        self.box.setFixedSize(20, 20)
        self.box.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.box)
        self.set_checked(checked)
        self._hover(False)

    def set_checked(self, on):
        self.checked = on
        r = 10 if self._radio else 5
        if on:
            self.box.setPixmap(icons.pixmap("check", 13, "#ffffff", 3))
            self.box.setStyleSheet(f"background: {theme.VAST[950]}; border-radius: {r}px;")
        else:
            self.box.clear()
            self.box.setStyleSheet(f"background: {theme.CARD}; border: 1.5px solid {theme.SAND[700]};"
                                   f" border-radius: {r}px;")

    def _hover(self, on):
        bg = theme.SAND[300] if on else "transparent"
        self.setStyleSheet(f"#CheckRow {{ background: {bg}; border-radius: 8px; }}")

    def enterEvent(self, e):
        self._hover(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover(False)
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


class LevelBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.0
        self.setFixedHeight(8)

    def set_level(self, v):
        self.level = max(0.0, min(1.0, v))
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.SECONDARY))
        r = QRectF(self.rect())
        p.drawRoundedRect(r, 4, 4)
        if self.level > 0.01:
            p.setBrush(QColor(theme.TEAL["mid"]))
            p.drawRoundedRect(QRectF(0, 0, max(8.0, r.width() * self.level), r.height()), 4, 4)


class KeyCapture(QFrame):
    """Shows a shortcut as keycaps; click it and press a chord to record a new one."""

    captured = Signal(str)
    rejected = Signal(str)

    def __init__(self, shortcut, allow_esc_alone=False, parent=None):
        self.capturing = False
        super().__init__(parent)
        self.setObjectName("KeyCapture")
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(250, 44)
        self.allow_esc_alone = allow_esc_alone
        self.capturing = False
        self.chord = set()
        self.shortcut = shortcut
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(12, 0, 12, 0)
        self.lay.setSpacing(6)
        self._render()

    def _render(self):
        _clear_layout(self.lay)
        if self.capturing:
            text = " + ".join(widgets.key_label(k) for k in chord_string(self.chord).split("+") if k)
            self.lay.addWidget(widgets.label(text or "Press keys…", 14, QFont.Weight.Medium,
                                             theme.FOREGROUND if text else theme.FOREGROUND_TERTIARY))
            self.lay.addStretch(1)
            border = f"2px solid {CAPTURE_BORDER}"
            bg = "#fbf8ff"
        else:
            if self.shortcut:
                self.lay.addWidget(widgets.KeyChips(self.shortcut, px=13), 0, Qt.AlignmentFlag.AlignVCenter)
            else:
                self.lay.addWidget(_muted("Not set", 14, wrap=False))
            self.lay.addStretch(1)
            pen = QLabel()
            pen.setPixmap(icons.pixmap("keyboard", 16, theme.FOREGROUND_TERTIARY))
            self.lay.addWidget(pen)
            border = f"1px solid {theme.SECONDARY}"
            bg = theme.CARD
        self.setStyleSheet(f"#KeyCapture {{ background: {bg}; border: {border}; border-radius: 8px; }}")

    def set_shortcut(self, shortcut):
        self.shortcut = shortcut
        self.capturing = False
        self._render()

    def start(self):
        self.capturing = True
        self.chord = set()
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self._render()

    def cancel(self):
        self.capturing = False
        self.chord = set()
        self._render()

    def _finish(self):
        keys = frozenset(self.chord)
        self.capturing = False
        self.chord = set()
        self._render()
        if keys:
            self.captured.emit(chord_string(keys))

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            if self.capturing:
                self.cancel()
            else:
                self.start()
        e.accept()

    def focusOutEvent(self, e):
        if self.capturing:
            # the Start menu can steal focus before the Win key's release arrives
            self._finish() if self.chord else self.cancel()
        super().focusOutEvent(e)

    def event(self, e):
        t = e.type()
        if not getattr(self, "capturing", False):
            return super().event(e)
        if t == QEvent.Type.ShortcutOverride:
            e.accept()
            return True
        if t == QEvent.Type.KeyPress:
            self._press(e)
            return True
        if t == QEvent.Type.KeyRelease:
            if not e.isAutoRepeat() and self.chord:
                self._finish()
            return True
        return super().event(e)

    def _press(self, e):
        if e.isAutoRepeat():
            return
        name = event_key_name(e)
        if name is None:
            self.cancel()
            self.rejected.emit("That key can't be part of a shortcut.")
            return
        if name == "esc" and not self.chord and not self.allow_esc_alone:
            self.cancel()
            return
        self.chord.add(name)
        if name not in MODIFIERS:
            self._finish()
        else:
            self._render()


# ----------------------------------------------------------------------------- dialogs
class ShortcutsDialog(widgets.Modal):
    def __init__(self, ctx, host, on_saved=None):
        super().__init__(host, 720, padding=32)
        self.ctx = ctx
        self.on_saved = on_saved
        self.draft = dict(ctx.settings.shortcuts)
        self.fields, self.errors = {}, {}
        self._pause(True)
        self.closed.connect(lambda: self._pause(False))

        self.body.setSpacing(4)
        self.body.addWidget(_title("Change shortcuts"))
        self.body.addWidget(_muted("Click a shortcut, then press the new key combination. Esc cancels.", 14))
        self.body.addSpacing(14)
        rows = QVBoxLayout()
        rows.setSpacing(0)
        for i, (key, text, hint) in enumerate(SHORTCUT_ACTIONS):
            if i:
                rows.addWidget(widgets.hline())
            row = QHBoxLayout()
            row.setContentsMargins(0, 9, 0, 9)
            col = QVBoxLayout()
            col.setSpacing(2)
            col.addWidget(widgets.label(text, 16, QFont.Weight.Medium))
            if hint:
                col.addWidget(_muted(hint, 13, wrap=False))
            err = _error_label()
            col.addWidget(err)
            row.addLayout(col, 1)
            field = KeyCapture(self.draft.get(key, ""), allow_esc_alone=(key == "dismiss"))
            field.captured.connect(lambda s, k=key: self._captured(k, s))
            field.rejected.connect(lambda msg, k=key: self._error(k, msg))
            row.addWidget(field, 0, Qt.AlignmentFlag.AlignVCenter)
            rows.addLayout(row)
            self.fields[key] = field
            self.errors[key] = err
        self.body.addLayout(rows)
        self.body.addSpacing(16)
        foot = QHBoxLayout()
        reset = widgets.button("Reset to default", "Ghost", self._reset)
        reset.setIcon(icons.icon("refresh", 15))
        foot.addWidget(reset)
        foot.addStretch(1)
        foot.addWidget(widgets.button("Cancel", "Secondary", self.close_modal))
        foot.addWidget(widgets.button("Done", "Primary", self._done))
        self.body.addLayout(foot)
        self.open()

    def _pause(self, on):
        fn = self.ctx.extras.get("pause_shortcuts")
        if fn:
            try:
                fn(on)
            except Exception:  # noqa: BLE001
                pass

    def _error(self, key, msg):
        lb = self.errors[key]
        lb.setText(msg or "")
        lb.setVisible(bool(msg))
        self.card.adjustSize()
        self._place()

    def _captured(self, key, shortcut):
        err = validate_chord(chord_keys(shortcut), key, self.draft)
        if err:
            self._error(key, err)
            self.fields[key].set_shortcut(self.draft.get(key, ""))
            return
        self.draft[key] = shortcut
        self.fields[key].set_shortcut(shortcut)
        self._error(key, "")

    def _reset(self):
        self.draft = default_shortcuts()
        for key, field in self.fields.items():
            field.set_shortcut(self.draft.get(key, ""))
            self._error(key, "")

    def _done(self):
        self.ctx.settings.shortcuts = dict(self.draft)
        self.ctx.save_settings()
        fn = self.ctx.extras.get("reload_shortcuts")
        if fn:
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                self.ctx.bus.toast.emit(f"Couldn't apply shortcuts: {e}")
        self.ctx.bus.toast.emit("Shortcuts saved")
        if self.on_saved:
            self.on_saved()
        self.close_modal()


class MicrophoneDialog(widgets.Modal):
    def __init__(self, ctx, host, on_saved=None):
        super().__init__(host, 540, padding=32)
        self.ctx = ctx
        self.on_saved = on_saved
        self.stream = None
        self._level = 0.0
        self.body.setSpacing(6)
        self.body.addWidget(_title("Microphone"))
        self.body.addWidget(_muted("Pick the microphone FlowLite listens to.", 14))
        self.body.addSpacing(10)
        holder = QWidget()
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(0, 0, 6, 0)
        self.list.setSpacing(2)
        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_scroll.setWidget(holder)
        _thin_scrollbar(self.list_scroll)
        self.body.addWidget(self.list_scroll)
        self.rows = []
        try:
            devices, default_name = input_devices()
        except Exception as e:  # noqa: BLE001
            devices, default_name = [], ""
            self.body.addWidget(_muted(f"Couldn't list microphones ({e}).", 13))
        current = ctx.settings.mic or ""
        self._add_row("", "Default", default_name or "Follows the Windows setting", current == "")
        for idx, name in devices:
            self._add_row(str(idx), name, "", current == str(idx))
        self.list_scroll.setFixedHeight(min(holder.sizeHint().height() + 2, 380))
        self.body.addSpacing(14)
        lv = QHBoxLayout()
        lv.setSpacing(12)
        lv.addWidget(_muted("Input level", 13, wrap=False))
        self.meter = LevelBar()
        lv.addWidget(self.meter, 1)
        self.body.addLayout(lv)
        self.meter_note = _muted("", 13)
        self.meter_note.hide()
        self.body.addWidget(self.meter_note)
        self.body.addSpacing(10)
        foot = QHBoxLayout()
        foot.addStretch(1)
        foot.addWidget(widgets.button("Done", "Primary", self.close_modal))
        self.body.addLayout(foot)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.meter.set_level(self._level))
        self.timer.start(50)
        self.closed.connect(self._stop_meter)
        self._start_meter(current)
        self.open()

    def _add_row(self, value, name, sub, checked):
        row = CheckRow(name, checked, radio=True, sub=sub)
        row.clicked.connect(lambda v=value: self._select(v))
        row.value = value
        self.list.addWidget(row)
        self.rows.append(row)

    def _select(self, value):
        for r in self.rows:
            r.set_checked(r.value == value)
        s = self.ctx.settings
        if s.mic == value:
            return
        s.mic = value
        self.ctx.save_settings()
        self._apply_to_recorder(int(value) if value.isdigit() else None)
        self._start_meter(value)
        if self.on_saved:
            self.on_saved()

    def _apply_to_recorder(self, device):
        rec = self.ctx.recorder
        if rec is None:
            return
        rec.device = device
        try:  # reopen a warm stream on the new device, unless a dictation is running
            if getattr(rec, "warm", False) and getattr(rec, "_stream", None) is not None \
                    and getattr(rec, "_sink", None) is None:
                rec.close()
                rec.warm = True
                rec._open()
        except Exception:  # noqa: BLE001
            pass

    def _start_meter(self, value):
        self._stop_meter()
        try:
            import numpy as np
            import sounddevice as sd

            def cb(indata, frames, t, status):
                rms = float(np.sqrt(np.mean(np.square(indata[:, 0])))) if frames else 0.0
                db = 20 * np.log10(max(rms, 1e-6))
                self._level = max(0.0, min(1.0, (db + 60) / 50))

            dev = int(value) if value.isdigit() else None
            self.stream = sd.InputStream(device=dev, channels=1, dtype="float32", callback=cb)
            self.stream.start()
            self.meter_note.hide()
        except Exception:  # noqa: BLE001
            self.stream = None
            self._level = 0.0
            self.meter_note.setText("This microphone can't be opened right now.")
            self.meter_note.show()

    def _stop_meter(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:  # noqa: BLE001
                pass
            self.stream = None
        self._level = 0.0


class LanguagesDialog(widgets.Modal):
    def __init__(self, ctx, host, on_saved=None):
        super().__init__(host, 580, 640, padding=32)
        self.ctx = ctx
        self.on_saved = on_saved
        self.selected = [c for c in ctx.settings.languages]
        self.auto = bool(ctx.settings.auto_detect_all)
        self.body.setSpacing(6)
        self.body.addWidget(_title("Dictation languages"))
        self.body.addWidget(_muted("Pick the languages you speak. Fewer languages make detection faster "
                                   "and more accurate.", 14))
        self.body.addSpacing(4)
        self.auto_toggle = widgets.Toggle(self.auto)
        self.auto_toggle.toggled.connect(self._set_auto)
        auto_row = widgets.SettingRow("Auto-detect", "Listen for any of Whisper's 99 languages.", self.auto_toggle)
        auto_row.layout().setContentsMargins(0, 8, 0, 8)
        self.body.addWidget(auto_row)
        self.search = widgets.SearchField("Search languages")
        self.search.textChanged.connect(lambda _: self._rebuild())
        self.body.addWidget(self.search)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        self.list = QVBoxLayout(holder)
        self.list.setContentsMargins(0, 6, 6, 6)
        self.list.setSpacing(2)
        self.scroll.setWidget(holder)
        _thin_scrollbar(self.scroll)
        self.body.addWidget(self.scroll, 1)
        self.auto_note = _muted("FlowLite will recognise whichever language you speak. Turn this off to "
                                "pick specific languages.", 14)
        self.auto_note.setContentsMargins(2, 8, 0, 0)
        self.auto_note.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.body.addWidget(self.auto_note, 1)
        self.error = _error_label()
        self.body.addWidget(self.error)
        foot = QHBoxLayout()
        self.count = _muted("", 13, wrap=False)
        foot.addWidget(self.count)
        foot.addStretch(1)
        foot.addWidget(widgets.button("Cancel", "Secondary", self.close_modal))
        foot.addWidget(widgets.button("Save and close", "Primary", self._save))
        self.body.addLayout(foot)
        self._set_auto(self.auto)
        self._rebuild()
        self.open()

    def _set_auto(self, on):
        self.auto = on
        self.scroll.setVisible(not on)
        self.search.setVisible(not on)
        self.auto_note.setVisible(on)
        self._update_count()

    def _update_count(self):
        if self.auto:
            self.count.setText("Auto-detecting all languages")
        else:
            n = len(self.selected)
            self.count.setText(f"{n} language{'s' if n != 1 else ''} selected")

    def _matches(self, code, q):
        english, native = LANGUAGES.get(code, (code, code))
        return not q or q == code or q in english.lower() or q in native.lower()

    def _rebuild(self):
        pos = self.scroll.verticalScrollBar().value()
        _clear_layout(self.list)
        q = self.search.text().strip().lower()
        chosen = [c for c in self.selected if self._matches(c, q)]
        rest = sorted((c for c in LANGUAGES if c not in self.selected and self._matches(c, q)),
                      key=lambda c: LANGUAGES[c][0])
        for title, codes in (("Selected", chosen), ("All languages", rest)):
            if not codes:
                continue
            if self.list.count():
                self.list.addSpacing(10)
            lb = widgets.section_label(title)
            lb.setContentsMargins(14, 4, 0, 4)
            self.list.addWidget(lb)
            for code in codes:
                row = CheckRow(language_label(code), code in self.selected)
                row.clicked.connect(lambda c=code: self._toggle(c))
                self.list.addWidget(row)
        if not chosen and not rest:
            empty = _muted("No languages match your search.", 14)
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.list.addWidget(empty)
        self.list.addStretch(1)
        self._update_count()
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(pos))

    def _toggle(self, code):
        if code in self.selected:
            self.selected.remove(code)
        else:
            self.selected.append(code)
        self.error.hide()
        self._rebuild()

    def _save(self):
        if not self.auto and not self.selected:
            self.error.setText("Pick at least one language, or turn on Auto-detect.")
            self.error.show()
            return
        s = self.ctx.settings
        s.languages = list(self.selected)
        s.auto_detect_all = self.auto
        self.ctx.save_settings()
        self.ctx.bus.toast.emit("Languages saved")
        if self.on_saved:
            self.on_saved()
        self.close_modal()


# ----------------------------------------------------------------------------- the modal
PANES = [  # key, title, icon, section
    ("general", "General", "sliders", "Settings"),
    ("system", "System", "laptop", "Settings"),
    ("models", "Models", "cpu", "Settings"),
    ("experimental", "Experimental", "zap", "Settings"),
    ("privacy", "Data and Privacy", "shield", "Privacy"),
]


class NavButton(QToolButton):
    def __init__(self, text, icon_name):
        super().__init__()
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.setIcon(icons.icon(icon_name, 18, theme.FOREGROUND, 1.8))
        self.setIconSize(QSize(18, 18))
        self.setText("  " + text)
        self.setFont(theme.ui_font(16, QFont.Weight.Normal))
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"QToolButton {{ background: transparent; border: none; border-radius: 8px;"
                           f" text-align: left; padding-left: 9px; font-size: 16px; }}"
                           f" QToolButton:hover {{ background: {theme.SAND[600]}; }}"
                           f" QToolButton:checked {{ background: {theme.SAND[600]}; }}")


class SettingsModal(widgets.Modal):
    def __init__(self, ctx, host_window, pane="general"):
        super().__init__(host_window, 960, 640, radius=12, padding=0)
        self.ctx = ctx
        self.pane = None
        self._gen = 0
        self.body.setSpacing(0)
        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._build_rail())
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        _thin_scrollbar(self.scroll)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 4, 40)
        rl.addWidget(self.scroll)
        h.addWidget(right, 1)
        self.body.addWidget(root)
        self.show_pane("general" if pane == "shortcuts" else pane)
        self.open()
        if pane == "shortcuts":
            ShortcutsDialog(ctx, host_window, self._refresh_general)

    # --- rail
    def _build_rail(self):
        rail = QFrame()
        rail.setObjectName("SettingsRail")
        rail.setFixedWidth(210)
        rail.setStyleSheet(f"#SettingsRail {{ background: {theme.TERTIARY}; border-right: 1px solid {theme.SECONDARY};"
                           f" border-top-left-radius: 12px; border-bottom-left-radius: 12px; }}")
        lay = QVBoxLayout(rail)
        lay.setContentsMargins(8, 20, 8, 20)
        lay.setSpacing(0)
        self.nav = {}
        section = None
        for key, text, icon_name, sec in PANES:
            if sec != section:
                if section is not None:
                    lay.addSpacing(10)
                    lay.addWidget(widgets.hline())
                    lay.addSpacing(14)
                lb = widgets.label(sec.upper(), 12, QFont.Weight.Medium, theme.SAND[950])
                f = lb.font()
                f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
                lb.setFont(f)
                lb.setContentsMargins(9, 0, 0, 0)
                lay.addWidget(lb)
                lay.addSpacing(12)
                section = sec
            b = NavButton(text, icon_name)
            b.clicked.connect(lambda _=False, k=key: self.show_pane(k))
            lay.addWidget(b)
            self.nav[key] = b
        lay.addStretch(1)
        foot = widgets.label(VERSION_TEXT, 13, color=theme.SAND[950])
        foot.setContentsMargins(9, 0, 0, 0)
        lay.addWidget(foot)
        return rail

    # --- panes
    def show_pane(self, key):
        if key not in self.nav:
            key = "general"
        self.pane = key
        self._gen += 1
        for k, b in self.nav.items():
            b.setChecked(k == key)
        old = self.scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        page = QWidget()
        page.setStyleSheet("background: transparent;")
        lay = QVBoxLayout(page)
        lay.setContentsMargins(44, 38, 44, 12)
        lay.setSpacing(0)
        title = dict((k, t) for k, t, _, _ in PANES)[key]
        lay.addWidget(widgets.display_label(title, 34))
        lay.addSpacing(26)
        getattr(self, f"_pane_{key}")(lay)
        lay.addStretch(1)
        self.scroll.setWidget(page)
        self.scroll.verticalScrollBar().setValue(0)

    def _heading(self, lay, text, first=False):
        if not first:
            lay.addSpacing(30)
        lay.addWidget(widgets.label(text, 17, QFont.Weight.Medium))
        lay.addSpacing(14)

    def _save(self, attr, value):
        setattr(self.ctx.settings, attr, value)
        self.ctx.save_settings()

    def _toggle_row(self, title, desc, attr, after=None):
        t = widgets.Toggle(bool(getattr(self.ctx.settings, attr)))

        def changed(on):
            self._save(attr, on)
            if after:
                after(on)
        t.toggled.connect(changed)
        return widgets.SettingRow(title, desc, t)

    def _extra(self, name):
        return self.ctx.extras.get(name)

    # General
    def _shortcut_html(self):
        keys = self.ctx.settings.shortcuts.get("push_to_talk", "")
        parts = [f'<span style="color:{theme.FOREGROUND}; font-weight:600">&nbsp;{widgets.key_label(k)}&nbsp;</span>'
                 for k in keys.split("+") if k]
        return f"Hold {' + '.join(parts)} and speak." if parts else "No push-to-talk shortcut set."

    def _pane_general(self, lay):
        g = widgets.SettingsGroup()
        self.row_shortcuts = g.add(widgets.SettingRow(
            "Shortcuts", self._shortcut_html(),
            _change(lambda: ShortcutsDialog(self.ctx, self.host, self._refresh_general))))
        self.row_mic = g.add(widgets.SettingRow(
            "Microphone", mic_display_name(self.ctx.settings),
            _change(lambda: MicrophoneDialog(self.ctx, self.host, self._refresh_general))))
        self.row_langs = g.add(widgets.SettingRow(
            "Dictation Languages", languages_summary(self.ctx.settings),
            _change(lambda: LanguagesDialog(self.ctx, self.host, self._refresh_general))))
        g.add(widgets.SettingRow("App Language", "The language FlowLite's windows use",
                                 _combo([("en", "English")], "en")))
        lay.addWidget(g)

    def _refresh_general(self):
        if self.pane != "general":
            return
        try:
            self.row_shortcuts.set_description(self._shortcut_html())
            self.row_mic.set_description(mic_display_name(self.ctx.settings))
            self.row_langs.set_description(languages_summary(self.ctx.settings))
        except RuntimeError:
            pass

    # System
    def _pane_system(self, lay):
        s = self.ctx.settings
        self._heading(lay, "App settings", first=True)
        g = widgets.SettingsGroup()
        enabled = False
        fn = self._extra("autostart_enabled")
        if fn:
            try:
                enabled = bool(fn())
            except Exception:  # noqa: BLE001
                enabled = False
        auto = widgets.Toggle(enabled)

        def set_auto(on):
            setter = self._extra("set_autostart")
            try:
                if setter:
                    setter(on)
            except Exception as e:  # noqa: BLE001
                auto.blockSignals(True)
                auto.setChecked(not on)
                auto.set_knob(1.0 if not on else 0.0)
                auto.blockSignals(False)
                self.ctx.bus.toast.emit(f"Couldn't change startup: {e}")
        auto.toggled.connect(set_auto)
        g.add(widgets.SettingRow("Launch app at login", "", auto))
        g.add(self._toggle_row("Show Flow Bar at all times", "", "show_resting_bar"))
        lay.addWidget(g)

        self._heading(lay, "Sound")
        g = widgets.SettingsGroup()
        g.add(self._toggle_row("Dictation and notification sounds", "", "sounds"))
        g.add(self._toggle_row("Mute all audio while dictating", "", "mute_media"))
        lay.addWidget(g)

        self._heading(lay, "Notifications")
        g = widgets.SettingsGroup()
        g.add(self._toggle_row("Suggestions", "Tips for getting more out of FlowLite.", "notify_suggestions"))
        g.add(self._toggle_row("Milestones", "A quick note when you hit a streak or word goal.", "notify_milestones"))
        lay.addWidget(g)

        self._heading(lay, "Extras")
        g = widgets.SettingsGroup()
        g.add(self._toggle_row("Auto-add to dictionary",
                               "When you fix a word FlowLite got wrong, remember the spelling.", "learn_from_edits"))
        level = (s.cleanup_level or "light").capitalize()

        def go_style():
            self.close_modal()
            self.ctx.bus.navigate.emit("style:cleanup")
        g.add(widgets.SettingRow("Smart formatting", f"Auto cleanup level: {level}",
                                 _change(go_style)))
        lay.addWidget(g)

    # Models
    def _pane_models(self, lay):
        s = self.ctx.settings
        gen = self._gen
        self._heading(lay, "Speech recognition", first=True)
        g = widgets.SettingsGroup()
        names = [n for n, _ in SPEECH_MODELS]
        items = list(SPEECH_MODELS)
        if s.whisper_model not in names:
            items.append((s.whisper_model, s.whisper_model))
        speech = _combo([], width=250)
        model = speech.model()
        for name, text in items:
            ok = whisper_downloaded(name) or name == s.whisper_model
            speech.addItem(text if ok else f"{text} (run setup to download)", name)
            if not ok and isinstance(model, QStandardItemModel):
                model.item(speech.count() - 1).setEnabled(False)
        speech.setCurrentIndex(max(0, speech.findData(s.whisper_model)))
        speech.view().setMinimumWidth(max(250, speech.view().sizeHintForColumn(0) + 32))
        note = widgets.SettingRow("Speech model", "Runs Whisper on this PC. Bigger models are more accurate "
                                                  "but slower. Takes effect after you restart FlowLite.", speech)

        def pick_speech(_i):
            value = speech.currentData()
            if value and value != s.whisper_model:
                self._save("whisper_model", value)
                self.ctx.bus.toast.emit("Restart FlowLite to load the new model")
        speech.currentIndexChanged.connect(pick_speech)
        g.add(note)
        lay.addWidget(g)

        self._heading(lay, "Formatting")
        g = widgets.SettingsGroup()
        llm = _combo([(s.llm_model, s.llm_model)], s.llm_model, width=250)
        status = widgets.SettingRow("Ollama", "Checking…")
        g.add(widgets.SettingRow("Formatting model", "A local Ollama model that adds punctuation and applies "
                                                      "your style.", llm))
        g.add(status)
        lay.addWidget(g)

        def pick_llm(_i):
            value = llm.currentData()
            if value and value != s.llm_model:
                self._save("llm_model", value)
                if self.ctx.formatter is not None and hasattr(self.ctx.formatter, "model"):
                    self.ctx.formatter.model = value
        llm.currentIndexChanged.connect(pick_llm)

        def got(models, err):
            if gen != self._gen:
                return
            ok_dot = f'<span style="color:{theme.RECORDING_FG}">●</span>'
            bad_dot = f'<span style="color:{ERROR_RED}">●</span>'
            if err is not None or models is None:
                status.set_description(f"{bad_dot}&nbsp; Not running. Start Ollama to turn on formatting; "
                                       "dictation still works without it.")
                return
            models = [m for m in models if m]
            llm.blockSignals(True)
            llm.clear()
            for m in ([s.llm_model] if s.llm_model not in models else []) + list(models):
                llm.addItem(m, m)
            llm.setCurrentIndex(max(0, llm.findData(s.llm_model)))
            llm.view().setMinimumWidth(max(250, llm.view().sizeHintForColumn(0) + 32))
            llm.blockSignals(False)
            n = len(models)
            status.set_description(f"{ok_dot}&nbsp; Running on this PC · {n} model{'s' if n != 1 else ''} "
                                   "installed")
        fn = self._extra("ollama_models")
        if fn:
            run_async(self, fn, got)
        else:
            got(None, RuntimeError("unavailable"))

    # Experimental
    def _pane_experimental(self, lay):
        s = self.ctx.settings
        keys = s.shortcuts.get("command_mode", "")
        keys_text = " + ".join(widgets.key_label(k) for k in keys.split("+") if k) or "the Command shortcut"
        g = widgets.SettingsGroup()
        g.add(self._toggle_row("Command Mode",
                               f"Select text, hold {keys_text} and say how to change it.",
                               "command_mode_enabled"))
        g.add(self._toggle_row("Press Enter command", "Say “press enter” at the end to send.",
                               "press_enter_command"))
        g.add(self._toggle_row("All lowercase", "Skip capital letters in everything you dictate.", "all_lowercase"))
        typing = widgets.Toggle(s.insert_mode == "type")
        typing.toggled.connect(lambda on: self._save("insert_mode", "type" if on else "paste"))
        g.add(widgets.SettingRow("Type instead of paste",
                                 "Types text key by key. Slower, but works in apps that block pasting.", typing))

        def warm(on):
            rec = self.ctx.recorder
            if rec is None:
                return
            try:
                if on:
                    rec.warm = True
                    rec._open()
                elif getattr(rec, "_sink", None) is None:
                    rec.close()
            except Exception:  # noqa: BLE001
                self.ctx.bus.toast.emit("Restart FlowLite to apply")
        g.add(self._toggle_row("Keep microphone warm",
                               "Keeps the mic open between dictations so your first word is never cut off. "
                               "The Windows mic indicator stays on.", "warm_mic", warm))
        lay.addWidget(g)

    # Data and Privacy
    def _pane_privacy(self, lay):
        s = self.ctx.settings
        hero = QFrame()
        hero.setObjectName("PrivacyHero")
        hero.setStyleSheet(f"#PrivacyHero {{ background: {theme.TERTIARY}; border-radius: 12px; }}")
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(24, 20, 24, 20)
        hl.setSpacing(16)
        badge = QLabel()
        badge.setFixedSize(44, 44)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setPixmap(icons.pixmap("lock", 20, theme.FOREGROUND))
        badge.setStyleSheet(f"background: {theme.CARD}; border: 1px solid {theme.SECONDARY}; border-radius: 22px;")
        hl.addWidget(badge, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(widgets.label("Everything stays on this computer", 16, QFont.Weight.Medium))
        col.addWidget(widgets.label("Speech recognition and formatting run locally. Your audio, transcripts "
                                    "and dictionary are never uploaded.", 15, color=theme.SAND[950], wrap=True))
        hl.addLayout(col, 1)
        lay.addWidget(hero)
        lay.addSpacing(16)

        g = widgets.SettingsGroup()
        g.add(self._toggle_row("Context awareness",
                               "Read a little text from the app you're dictating into, so names and terms "
                               "come out right. It never leaves this PC.", "read_context"))
        g.add(self._toggle_row("Keep recordings",
                               "Save the audio of each dictation so you can replay or retry it from Home.",
                               "save_audio"))
        storage = _combo([("keep", "Store data locally"), ("auto_delete_24h", "Auto-delete after 24 hours"),
                          ("never", "Never store history")], s.local_storage, width=210)
        storage.currentIndexChanged.connect(lambda _i: self._storage_changed(storage))
        g.add(widgets.SettingRow("Local data storage", "Choose how long FlowLite keeps your dictation history.",
                                 storage))
        lay.addWidget(g)

        self._heading(lay, "Your data")
        g = widgets.SettingsGroup()
        self.import_btn = _change(self._import_wispr, "Import")
        g.add(widgets.SettingRow("Import from Wispr Flow",
                                 "Copy history, dictionary and snippets from Wispr Flow on this PC.",
                                 self.import_btn))
        folder = _change(self._open_folder, "Open folder")
        g.add(widgets.SettingRow("Data folder", str(store.DATA_DIR), folder))
        g.add(widgets.SettingRow("Delete all history", "Permanently remove every saved dictation and recording.",
                                 _danger_button("Delete", self._delete_history)))
        lay.addWidget(g)

    def _storage_changed(self, combo):
        s = self.ctx.settings
        value = combo.currentData()
        prev = s.local_storage
        if value == prev:
            return

        def set_combo(v):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(v)))
            combo.blockSignals(False)

        def apply():
            self._save("local_storage", value)
            set_combo(value)
            if value == "never":
                self.ctx.db.execute("delete from history")
            elif value == "auto_delete_24h":
                self.ctx.db.execute("delete from history where ts < ?", (time.time() - 86400,))
            self.ctx.bus.history_changed.emit()
            self.ctx.bus.toast.emit("Storage setting saved")

        if value == "keep":
            self._save("local_storage", value)
            return
        set_combo(prev)  # stays unchanged unless confirmed
        if value == "never":
            title, body = "Stop saving history?", "FlowLite will delete your existing history now and stop saving new dictations."
        else:
            title, body = "Auto-delete history?", "Dictations older than 24 hours will be deleted now, and newer ones after a day."
        widgets.confirm(self.host, title, body, "Delete and continue", apply, danger=True)

    def _import_wispr(self):
        fn = self._extra("import_wispr")
        if not fn:
            self.ctx.bus.toast.emit("Import isn't available")
            return
        btn = self.import_btn
        btn.setEnabled(False)
        btn.setText("Importing…")

        def done(res, err):
            try:
                btn.setEnabled(True)
                btn.setText("Import")
            except RuntimeError:
                pass
            if err is not None:
                self.ctx.bus.toast.emit(f"Import failed: {err}")
                return
            res = res or {}
            if not any(res.get(k) for k in ("history", "words", "snippets")):
                self.ctx.bus.toast.emit("Nothing new to import from Wispr Flow")
            else:
                self.ctx.bus.toast.emit(f"Imported {res.get('history', 0)} dictations, {res.get('words', 0)} words, "
                                        f"{res.get('snippets', 0)} snippets")
            self.ctx.bus.history_changed.emit()
            self.ctx.bus.dictionary_changed.emit()
        run_async(QCoreApplication.instance() or self, fn, done)  # outlives the modal: still toasts + refreshes

    def _open_folder(self):
        try:
            store.DATA_DIR.mkdir(parents=True, exist_ok=True)
            os.startfile(store.DATA_DIR)  # noqa: S606 - local folder
        except OSError as e:
            self.ctx.bus.toast.emit(f"Couldn't open folder: {e}")

    def _delete_history(self):
        def go():
            self.ctx.db.execute("delete from history")
            self.ctx.bus.history_changed.emit()
            self.ctx.bus.toast.emit("History deleted")
        widgets.confirm(self.host, "Delete all history?",
                        "Every saved dictation and recording on this PC will be removed. This can't be undone.",
                        "Delete everything", go, danger=True)
