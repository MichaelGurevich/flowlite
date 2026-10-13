"""Home: greeting, rotating tip banner, quick stats and the dictation history.

Layout follows Wispr Flow's hub home (two columns: banner + history on the left,
stats card on the right); all copy and code are FlowLite's own.
"""

import datetime as dt
import io
import threading
import wave

from PySide6.QtCore import QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QGuiApplication
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from .. import icons, theme, widgets

PAGE_SIZE = 100


def _keys_text(shortcut):
    return " + ".join(widgets.key_label(k) for k in (shortcut or "").split("+") if k)


def _time_text(ts):
    t = dt.datetime.fromtimestamp(ts)
    hour = t.hour % 12 or 12
    return f"{hour}:{t.minute:02d}{'am' if t.hour < 12 else 'pm'}"


def _day_text(day):
    today = dt.date.today()
    if day == today:
        return "Today"
    if day == today - dt.timedelta(days=1):
        return "Yesterday"
    return f"{day.strftime('%B')} {day.day}, {day.year}"


def _caps_label(text, px=13, color=theme.SAND[950], weight=QFont.Weight.DemiBold):
    lb = widgets.label(text.upper(), px, weight, color)
    f = lb.font()
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.3)
    lb.setFont(f)
    return lb


def _decode_wav(blob):
    """WAV bytes -> (float32 frames array, sample rate)."""
    import numpy as np
    with wave.open(io.BytesIO(blob)) as w:
        rate, channels, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width == 2:
        data = np.frombuffer(raw, dtype="<i2").astype("float32") / 32768.0
    elif width == 4:
        data = np.frombuffer(raw, dtype="<i4").astype("float32") / 2147483648.0
    elif width == 1:
        data = (np.frombuffer(raw, dtype="u1").astype("float32") - 128.0) / 128.0
    else:
        raise ValueError(f"unsupported sample width {width}")
    if channels > 1:
        data = data.reshape(-1, channels)
    return data, rate


_AUDIO_LOCK = threading.Lock()


def _audio_async(fn, on_error=None):
    """Run fn(sounddevice) on a worker thread, one audio operation at a time."""
    def run():
        with _AUDIO_LOCK:
            try:
                import sounddevice as sd
            except Exception as e:  # noqa: BLE001 - no audio stack
                if on_error:
                    on_error(e)
                return
            try:
                fn(sd)
            except Exception as e:  # noqa: BLE001
                if on_error:
                    on_error(e)
    threading.Thread(target=run, daemon=True, name="history-audio").start()


class _Signals(QObject):
    play_started = Signal(int, int, int)     # history id, token, duration ms
    play_failed = Signal(int, int, str)      # history id, token, message
    retried = Signal(int, object)            # history id, new text or None


# ----------------------------------------------------------------------------- tips
def _tips(settings):
    ptt = _keys_text(settings.shortcuts.get("push_to_talk", "ctrl+win"))
    cmd = _keys_text(settings.shortcuts.get("command_mode", "ctrl+win+alt"))
    t1 = _keys_text(settings.shortcuts.get("transform_1", "win+alt+1"))
    return [
        ("Talk <i>hands-free</i> for longer thoughts",
         f"Double-tap {ptt} and FlowLite keeps listening until you tap again.",
         "Shortcut settings", ("settings", "general")),
        ("Stop re-typing the <i>same</i> things",
         "Save a snippet once, then just say its trigger to drop in the full text.",
         "Create a snippet", ("page", "snippets")),
        ("Edit text by <i>asking</i> for it",
         f"Select some text, hold {cmd} and say what to change. It runs on this PC.",
         "Command Mode settings", ("settings", "experimental")),
        ("Teach FlowLite <i>your</i> words",
         "Names, products and jargon in your dictionary come out spelled right.",
         "Open dictionary", ("page", "dictionary")),
        ("Polish any text in <i>one</i> keystroke",
         f"Select text anywhere and press {t1} to rewrite it with a local model.",
         "See transforms", ("page", "transforms")),
    ]


# ----------------------------------------------------------------------------- stats card
class StatsCard(QFrame):
    """Sand card: total words / wpm / streak (click -> Insights) + a voice-profile teaser."""

    open_insights = Signal()
    open_voice = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("StatsCard")
        self.setStyleSheet(f"#StatsCard {{ background: {theme.TERTIARY}; border: 1px solid {theme.SECONDARY};"
                           f" border-radius: 16px; }}")
        self.setFixedWidth(310)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Open Insights")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        top = QVBoxLayout()
        top.setContentsMargins(30, 26, 24, 24)
        top.setSpacing(6)
        self.lines = []
        for _ in range(3):
            lb = QLabel()
            lb.setTextFormat(Qt.TextFormat.RichText)
            lb.setStyleSheet("background: transparent;")
            lb.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            top.addWidget(lb)
            self.lines.append(lb)
        lay.addLayout(top)

        self.teaser = QWidget()
        self.teaser.setCursor(Qt.CursorShape.ArrowCursor)
        tl = QVBoxLayout(self.teaser)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        tl.addWidget(widgets.hline())
        inner = QVBoxLayout()
        inner.setContentsMargins(30, 22, 24, 28)
        inner.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(widgets.label("Your voice profile", 18, QFont.Weight.DemiBold))
        head.addStretch(1)
        close = widgets.IconButton("close", "Hide", 14, 26, theme.FOREGROUND_TERTIARY)
        close.clicked.connect(self.teaser.hide)
        head.addWidget(close)
        inner.addLayout(head)
        inner.addWidget(widgets.label("See your favourite words, busiest hours and languages.", 15,
                                      color=theme.SAND[950], wrap=True))
        inner.addSpacing(14)
        go = QPushButton("Explore my voice")
        go.setCursor(Qt.CursorShape.PointingHandCursor)
        go.setFont(theme.ui_font(16, QFont.Weight.Medium))
        go.setStyleSheet(f"QPushButton {{ background: {theme.ORANGE}; color: {theme.FOREGROUND};"
                         f" border: 1.5px solid #c9781f; border-radius: 8px; padding: 9px 16px; }}"
                         f" QPushButton:hover {{ background: #ffb862; }}")
        go.clicked.connect(self.open_voice)
        inner.addWidget(go)
        tl.addLayout(inner)
        lay.addWidget(self.teaser)

    def set_stats(self, total_words, wpm, streak):
        fam = theme.DISPLAY_FAMILY
        rows = [(f"{total_words:,}", "total words"), (f"{wpm:,}", "wpm"),
                (f"{streak:,}", "day streak")]
        for lb, (num, unit) in zip(self.lines, rows):
            lb.setText(f'<span style="font-family: \'{fam}\'; font-size: 34px; color: {theme.FOREGROUND};">'
                       f'{num}</span>&nbsp;&nbsp;<span style="font-size: 17px; color: {theme.FOREGROUND};">'
                       f'{unit}</span>')

    def mousePressEvent(self, e):
        e.accept()

    def mouseReleaseEvent(self, e):
        in_stats = not self.teaser.isVisible() or e.position().y() < self.teaser.y()
        if e.button() == Qt.MouseButton.LeftButton and in_stats:
            self.open_insights.emit()
        super().mouseReleaseEvent(e)


# ----------------------------------------------------------------------------- history row
class HistoryRow(widgets.HoverRow):
    def __init__(self, page, row):
        super().__init__(min_height=64)
        self.page = page
        self.row = row
        self.hid = row["id"]
        self.final = row["final_text"] or row["asr_text"] or ""
        self.original = row["asr_text"] or ""
        self.showing_original = False
        self.lay.setContentsMargins(18, 14, 14, 14)
        self.lay.setSpacing(12)

        tm = widgets.label(_time_text(row["ts"]), 15, color=theme.FOREGROUND_TERTIARY)
        tm.setFixedWidth(88)
        tm.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.lay.addWidget(tm, 0, Qt.AlignmentFlag.AlignVCenter)

        self.text = widgets.label(self.final, 16, wrap=True)
        self.text.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter)
        self.text.setTextFormat(Qt.TextFormat.PlainText)
        self.text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.text.setCursor(Qt.CursorShape.IBeamCursor)
        self.text.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        if row.get("status") not in (None, "ok"):
            self.text.setStyleSheet(f"color: {theme.FOREGROUND_TERTIARY}; background: transparent;")
        self.lay.addWidget(self.text, 1)

        actions = QWidget()
        al = QHBoxLayout(actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(4)
        self.play_btn = None
        if row.get("has_audio"):
            self.play_btn = widgets.IconButton("play", "Play recording", 18, 34)
            self.play_btn.clicked.connect(lambda: page.toggle_play(self.hid))
            al.addWidget(self.play_btn)
        copy = widgets.IconButton("copy", "Copy", 18, 34)
        copy.clicked.connect(self.copy)
        al.addWidget(copy)
        if self.original and self.original.strip() != self.final.strip():
            self.undo_btn = widgets.IconButton("undo", "Show original", 18, 34)
            self.undo_btn.setCheckable(True)
            self.undo_btn.setChecked(False)
            self.undo_btn.clicked.connect(self.toggle_original)
            al.addWidget(self.undo_btn)
        more = widgets.IconButton("more", "More", 18, 34)
        more.clicked.connect(lambda: self.show_menu(more))
        al.addWidget(more)
        actions.setFixedWidth(4 * 34 + 3 * 4)
        al.insertStretch(0, 1)
        sp = actions.sizePolicy()
        sp.setRetainSizeWhenHidden(True)
        actions.setSizePolicy(sp)
        self.set_actions(actions)

    def current_text(self):
        return self.original if self.showing_original else self.final

    def copy(self):
        QGuiApplication.clipboard().setText(self.current_text())
        self.page.ctx.bus.toast.emit("Copied")

    def toggle_original(self):
        self.showing_original = not self.showing_original
        self.text.setText(self.current_text())
        self.undo_btn.setToolTip("Show edited" if self.showing_original else "Show original")
        self.undo_btn.setChecked(self.showing_original)

    def set_playing(self, playing):
        if self.play_btn:
            self.play_btn.setIcon(icons.icon("stop" if playing else "play", 18, theme.FOREGROUND))
            self.play_btn.setToolTip("Stop" if playing else "Play recording")

    def show_menu(self, anchor):
        m = QMenu(self)
        m.addAction("Copy original transcript", self.copy_original)
        retry = m.addAction("Retry transcript", lambda: self.page.retry(self.hid))
        retry.setEnabled(bool(self.row.get("has_audio")) and "retry" in self.page.ctx.extras)
        m.addSeparator()
        m.addAction("Delete", lambda: self.page.delete(self.hid))
        m.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def copy_original(self):
        QGuiApplication.clipboard().setText(self.original or self.final)
        self.page.ctx.bus.toast.emit("Copied original")


# ----------------------------------------------------------------------------- page
class HomePage(QWidget):
    MAX_WIDTH = 1100

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.limit = PAGE_SIZE
        self.search = ""
        self.tip_index = 0
        self.rows = {}
        self.playing = None          # history id being played
        self.play_token = 0
        self.dirty = True
        self.sig = _Signals()
        self.sig.play_started.connect(self._on_play_started)
        self.sig.play_failed.connect(self._on_play_failed)
        self.sig.retried.connect(self._on_retried)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(28)
        self.greeting = widgets.label("", 30, QFont.Weight.DemiBold)
        root.addWidget(self.greeting)

        cols = QHBoxLayout()
        cols.setSpacing(24)
        root.addLayout(cols)
        left = QVBoxLayout()
        left.setSpacing(0)
        cols.addLayout(left, 1)

        # --- tip banner
        self.hero = widgets.Hero("", "", "lagoon", height=200)
        self.hero.title.setStyleSheet(f'color: #fcfcfb; background: transparent;'
                                      f' font-family: "{theme.DISPLAY_FAMILY}"; font-size: 36px;')
        self.hero.layout().setContentsMargins(36, 30, 36, 30)
        self.hero_btn = self.hero.add_button("", self._tip_action)
        self.hero.dismissed.connect(lambda: self.hero_gap.hide())
        left.addWidget(self.hero)
        self.hero_gap = QWidget()
        self.hero_gap.setFixedHeight(40)
        left.addWidget(self.hero_gap)
        self._show_tip()
        self.tip_timer = QTimer(self)
        self.tip_timer.setInterval(20000)
        self.tip_timer.timeout.connect(self.next_tip)
        self.tip_timer.start()

        # --- history
        self.search_row = QWidget()
        sr = QHBoxLayout(self.search_row)
        sr.setContentsMargins(0, 0, 0, 16)
        sr.setSpacing(8)
        self.search_field = widgets.SearchField("Search your dictations")
        self.search_field.textChanged.connect(lambda _: self.search_timer.start())
        sr.addWidget(self.search_field, 1)
        close = widgets.IconButton("close", "Close search", 16, 34)
        close.clicked.connect(self.close_search)
        sr.addWidget(close)
        self.search_row.hide()
        left.addWidget(self.search_row)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(250)
        self.search_timer.timeout.connect(self._apply_search)

        self.history_box = QVBoxLayout()
        self.history_box.setSpacing(0)
        left.addLayout(self.history_box)
        self.more_btn = widgets.button("Load more", "Secondary", self.load_more)
        more_row = QHBoxLayout()
        more_row.setContentsMargins(0, 20, 0, 0)
        more_row.addStretch(1)
        more_row.addWidget(self.more_btn)
        more_row.addStretch(1)
        left.addLayout(more_row)
        left.addStretch(1)

        # --- right column
        right = QVBoxLayout()
        right.setSpacing(0)
        self.stats = StatsCard()
        self.stats.open_insights.connect(lambda: ctx.bus.navigate.emit("insights"))
        self.stats.open_voice.connect(self._open_voice)
        right.addWidget(self.stats)
        right.addStretch(1)
        cols.addLayout(right, 0)

        ctx.bus.history_changed.connect(self._on_history_changed)
        ctx.bus.settings_changed.connect(self._update_header)
        self.refresh()

    # ------------------------------------------------------------------ header / tips
    def _update_header(self):
        name = (self.ctx.settings.first_name or "").strip()
        self.greeting.setText(f"Welcome back, {name}" if name else "Welcome back")
        self._show_tip()

    def _show_tip(self):
        tips = _tips(self.ctx.settings)
        title, body, btn, _ = tips[self.tip_index % len(tips)]
        self.hero.title.setText(title)
        self.hero.body.setText(body)
        self.hero_btn.setText(btn)

    def next_tip(self):
        if self.hero.isVisible() and self.isVisible():
            self.tip_index += 1
            self._show_tip()

    def _tip_action(self):
        tips = _tips(self.ctx.settings)
        kind, key = tips[self.tip_index % len(tips)][3]
        if kind == "page":
            self.ctx.bus.navigate.emit(key)
        else:
            self.ctx.bus.open_settings.emit(key)

    def _open_voice(self):
        from . import insights
        insights.request_tab("voice")
        self.ctx.bus.navigate.emit("insights")

    # ------------------------------------------------------------------ data
    def refresh(self):
        self._update_header()
        st = self.ctx.history.stats()
        self.stats.set_stats(st["total_words"], st["wpm"], st["day_streak"])
        if self.dirty:
            self._load_history()

    def _on_history_changed(self):
        self.dirty = True
        if self.isVisible():
            self.refresh()

    def load_more(self):
        self.limit += PAGE_SIZE
        self._load_history()

    def toggle_search(self):
        if self.search_row.isVisible():
            self.close_search()
        else:
            self.search_row.show()
            self.search_field.setFocus()

    def close_search(self):
        self.search_row.hide()
        if self.search_field.text():
            self.search_field.clear()
            self._apply_search()

    def _apply_search(self):
        self.search = self.search_field.text().strip()
        self.limit = PAGE_SIZE
        self._load_history()

    def _clear_history(self):
        while self.history_box.count():
            item = self.history_box.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self.rows = {}

    def _group_header(self, text, first):
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0 if first else 32, 0, 12)
        lay.setSpacing(8)
        lay.addWidget(_caps_label(text), 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addStretch(1)
        if first:
            btn = widgets.IconButton("search", "Search history", 18, 30, theme.FOREGROUND_TERTIARY)
            btn.clicked.connect(self.toggle_search)
            lay.addWidget(btn)
        else:
            lay.addSpacing(30)
        w.setFixedHeight((0 if first else 32) + 12 + 30)
        return w

    def _load_history(self):
        self.dirty = False
        rows = self.ctx.history.recent(self.limit + 1, 0, self.search)
        has_more = len(rows) > self.limit
        rows = rows[:self.limit]
        self.setUpdatesEnabled(False)
        self._clear_history()
        if not rows:
            if self.search:
                self.history_box.addWidget(self._group_header("Search results", True))
                self.history_box.addWidget(widgets.EmptyState(
                    "search", "No matches", f"Nothing in your history mentions “{self.search}”."))
            else:
                ptt = _keys_text(self.ctx.settings.shortcuts.get("push_to_talk", "ctrl+win"))
                self.history_box.addWidget(self._group_header("Today", True))
                card = widgets.ListCard()
                card.add(widgets.EmptyState("mic", "No dictations yet",
                                            f"Hold {ptt} anywhere and start talking."))
                self.history_box.addWidget(card)
        else:
            card, day = None, None
            for r in rows:
                d = dt.date.fromtimestamp(r["ts"])
                if d != day:
                    day = d
                    self.history_box.addWidget(self._group_header(_day_text(d), card is None))
                    card = widgets.ListCard()
                    self.history_box.addWidget(card)
                row = HistoryRow(self, r)
                if r["id"] == self.playing:
                    row.set_playing(True)
                card.add(row)
                self.rows[r["id"]] = row
        self.more_btn.setVisible(has_more)
        self.setUpdatesEnabled(True)

    # ------------------------------------------------------------------ playback
    def toggle_play(self, hid):
        """Play the saved WAV for a row; a second click (or another row) stops it.

        PortAudio init, decoding and stream start/stop all happen on a worker thread.
        """
        was = self.playing
        self._set_playing(None)
        self.play_token += 1
        token = self.play_token
        if was == hid:
            _audio_async(lambda sd: sd.stop())
            return
        self._set_playing(hid)

        def work(sd):
            try:
                sd.stop()
                row = self.ctx.history.get(hid)
                if not row or not row.get("audio"):
                    raise ValueError("No recording saved for this dictation")
                data, rate = _decode_wav(row["audio"])
                if token != self.play_token:
                    return
                sd.play(data, rate)
                self.sig.play_started.emit(hid, token, int(len(data) * 1000 / rate) + 150)
            except Exception as e:  # noqa: BLE001
                self.sig.play_failed.emit(hid, token, str(e))
        _audio_async(work, lambda e: self.sig.play_failed.emit(hid, token, str(e)))

    def _set_playing(self, hid):
        if self.playing in self.rows:
            self.rows[self.playing].set_playing(False)
        self.playing = hid
        if hid in self.rows:
            self.rows[hid].set_playing(True)

    def _on_play_started(self, hid, token, ms):
        QTimer.singleShot(ms, lambda: self._play_done(token))

    def _play_done(self, token):
        if token == self.play_token:
            self._set_playing(None)

    def _on_play_failed(self, hid, token, msg):
        if token == self.play_token:
            self._set_playing(None)
            self.ctx.bus.toast.emit("Couldn't play this recording")

    # ------------------------------------------------------------------ retry / delete
    def retry(self, hid):
        fn = self.ctx.extras.get("retry")
        if not fn:
            return
        self.ctx.bus.toast.emit("Transcribing again…")

        def work():
            try:
                text = fn(hid)
            except Exception:  # noqa: BLE001
                text = None
            if text:
                row = self.ctx.history.get(hid)
                if row and (row.get("final_text") or "") != text:
                    self.ctx.db.update("history", hid, final_text=text, words=len(text.split()))
            self.sig.retried.emit(hid, text)
        threading.Thread(target=work, daemon=True, name="history-retry").start()

    def _on_retried(self, hid, text):
        self.ctx.bus.toast.emit("Transcript updated" if text else "Couldn't retry this one")
        if text:
            self.ctx.bus.history_changed.emit()

    def delete(self, hid):
        def go():
            if self.playing == hid:
                self.play_token += 1
                self._set_playing(None)
                _audio_async(lambda sd: sd.stop())
            self.ctx.history.delete(hid)
            self.ctx.bus.history_changed.emit()
            self.ctx.bus.toast.emit("Deleted")
        widgets.confirm(self.window(), "Delete this dictation?",
                        "It will be removed from your history on this computer. This can't be undone.",
                        "Delete", go, danger=True)
