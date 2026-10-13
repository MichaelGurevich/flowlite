"""Insights: usage numbers (speed, fixes, words, apps, streak heatmap) and a local voice profile.

Layout follows Wispr Flow's Insights page; everything is computed from the local history
database, and the copy and code are FlowLite's own.
"""

import collections
import datetime as dt
import re
import threading
import time

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QStackedWidget,
                               QToolTip, QVBoxLayout, QWidget)

from .. import icons, theme, widgets

icons.PATHS.setdefault("trend_up", '<polyline points="22 7 13.5 15.5 8.5 10.5 2 17"/>'
                                   '<polyline points="16 7 22 7 22 13"/>')
icons.PATHS.setdefault("trend_down", '<polyline points="22 17 13.5 8.5 8.5 13.5 2 7"/>'
                                     '<polyline points="16 17 22 17 22 11"/>')
icons.PATHS.setdefault("chevron_left", '<path d="m15 18-6-6 6-6"/>')
icons.PATHS.setdefault("chevron_right", '<path d="m9 18 6-6-6-6"/>')
icons.PATHS.setdefault("clock", '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>')

_REQUESTED_TAB = None
TAB_KEYS = ["usage", "voice"]


def request_tab(name):
    """Ask the page to open on a tab next time it is shown ("usage" | "voice")."""
    global _REQUESTED_TAB
    _REQUESTED_TAB = name


# ----------------------------------------------------------------------------- helpers
HEAT = {"future": "#e8e4dc", "zero": theme.TEAL["empty"], 1: theme.TEAL["pale"], 2: theme.TEAL["light"],
        3: theme.TEAL["mid"], 4: theme.TEAL["dark"]}

LANG_NAMES = {"en": "English", "he": "Hebrew", "iw": "Hebrew", "ru": "Russian", "uk": "Ukrainian",
              "de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "pt": "Portuguese",
              "nl": "Dutch", "pl": "Polish", "tr": "Turkish", "ar": "Arabic", "zh": "Chinese",
              "ja": "Japanese", "ko": "Korean", "hi": "Hindi", "sv": "Swedish", "fi": "Finnish",
              "cs": "Czech", "el": "Greek", "ro": "Romanian", "hu": "Hungarian", "da": "Danish",
              "no": "Norwegian", "fa": "Persian", "yi": "Yiddish", "be": "Belarusian"}

STOPWORDS = set("""
a about above after again against all also am an and any are aren as at be because been before being below
between both but by can could did didn do does doesn doing don down during each few for from further get got
had has have having he her here hers herself him himself his how i if in into is isn it its itself just let
like me more most my myself no nor not now of off on once only or other our ours ourselves out over own really
same she should so some such than that the their theirs them themselves then there these they this those
through to too under until up very was wasn we were what when where which while who whom why will with would
you your yours yourself yourselves yeah okay ok um uh gonna wanna want going one thing things know think
something maybe actually right well also even still make way much many need use used using sure kind lot
i'm it's don't that's i'll i've you're can't didn't doesn't isn't we're let's there's what's i'd won't
אני אתה את הוא היא אנחנו אתם הם הן של על עם זה זאת זו לא כן גם אבל או כי אם מה מי איך למה כמו יש אין
היה הייתה היו להיות כל עוד רק כבר אז שלי שלך שלו שלה אותו אותה אותי לי לך לו לה להם ממש פה שם עכשיו
и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от
меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж
вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтобы без
будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом один
почти мой тем чтоб нее были куда зачем всех никогда можно при наконец два об другой хоть после над больше
тот через эти нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше
чуть том нельзя такой им более всегда конечно всю между это эта
""".split())

WORD_RE = re.compile(r"[^\W\d_][\w'’-]*", re.UNICODE)


def _caps_label(text, px=13, color=theme.SAND[900], weight=QFont.Weight.DemiBold, spacing=1.4):
    lb = widgets.label(text.upper(), px, weight, color)
    f = lb.font()
    f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    lb.setFont(f)
    return lb


def _big_number(text, px=34):
    return widgets.label(text, px, QFont.Weight.Medium)


def _info(tip, size=16):
    ic = QLabel()
    ic.setPixmap(icons.pixmap("info", size, theme.VAST[400], 1.6))
    ic.setToolTip(tip)
    ic.setStyleSheet("background: transparent;")
    return ic


def _card(padding=22):
    c = widgets.Card(theme.TERTIARY, 16, theme.SECONDARY, padding)
    c.lay.setSpacing(6)
    return c


def speed_rank(wpm):
    """(gauge text, tooltip) from the speaking speed; percent of people you out-talk."""
    if wpm <= 0:
        return None, "Dictate a few sentences to measure your speed."
    if wpm < 40:
        return None, "Keep talking: speed picks up as dictation becomes a habit."
    for limit, top, line in ((75, "10%", "That's quicker than about 9 in 10 typists."),
                             (85, "5%", "That's quicker than about 95% of typists."),
                             (95, "3%", "That's quicker than about 97% of typists."),
                             (105, "2%", "Very few people type this fast."),
                             (125, "1%", "You out-talk almost every keyboard."),
                             (135, "0.5%", "You speak faster than nearly anyone types.")):
        if wpm < limit:
            return top, line
    return "0.1%", "Practically a live captioner."


def comparison_line(total):
    if total <= 0:
        return "Your first words will show up here."
    for size, one, many in ((90000, "novel", "novels"), (1000, "essay", "essays"),
                            (120, "email", "emails"), (30, "tweet", "tweets")):
        if total >= size:
            n = total // size
            return f"That's about {n:,} {one if n == 1 else many} worth of writing!"
    return f"{total:,} words and counting. Keep going!"


# ----------------------------------------------------------------------------- painted widgets
class Gauge(QWidget):
    """Semicircle speed gauge with "Top x%" in the middle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(200, 112)
        self.fraction = 0.0
        self.top = None

    def set_value(self, fraction, top):
        self.fraction = max(0.0, min(1.0, fraction))
        self.top = top
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        stroke = 14
        d = self.width() - stroke
        rect = QRectF(stroke / 2, stroke / 2, d, d)
        pen = QPen(QColor(theme.SECONDARY), stroke)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(rect, 180 * 16, -180 * 16)
        if self.fraction > 0:
            pen.setColor(QColor(theme.TEAL["dark"]))
            p.setPen(pen)
            p.drawArc(rect, 180 * 16, int(-180 * 16 * self.fraction))
        cx = self.width() / 2
        if self.top:
            p.setPen(QColor(theme.FOREGROUND_TERTIARY))
            p.setFont(theme.ui_font(17))
            p.drawText(QRectF(0, 42, self.width(), 24), Qt.AlignmentFlag.AlignCenter, "Top")
            p.setPen(QColor(theme.FOREGROUND))
            p.setFont(theme.ui_font(23, QFont.Weight.Medium))
            p.drawText(QRectF(0, 68, self.width(), 32), Qt.AlignmentFlag.AlignCenter, self.top)
        else:
            p.setPen(QColor(theme.FOREGROUND_TERTIARY))
            p.setFont(theme.ui_font(16, QFont.Weight.Medium))
            p.drawText(QRectF(cx - 70, 60, 140, 40), Qt.AlignmentFlag.AlignCenter, "Keep going")


class PctBar(QWidget):
    """Rounded teal bar whose width follows a percentage, with the number inside."""

    def __init__(self, pct, color, max_width, parent=None):
        super().__init__(parent)
        self.pct, self.color = pct, color
        self.max_width = max_width
        self.setFixedHeight(32)
        self.setFixedWidth(max(44, int(max_width * pct / 100)))

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(QRectF(self.rect()), 3, 3)
        p.setPen(QColor("#ffffff"))
        p.setFont(theme.ui_font(14, QFont.Weight.DemiBold))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"{self.pct}%")


class Heatmap(QWidget):
    """GitHub-style grid of words per day: columns are weeks (Sun..Sat), newest on the right."""

    CELL, GAP, LEFT, TOP = 18, 7, 40, 26
    resized = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.days = {}
        self.offset_weeks = 0
        self.thresholds = (1, 2, 3)
        self.setMouseTracking(True)
        self.setMinimumWidth(self.LEFT + 10 * (self.CELL + self.GAP))
        self.setFixedHeight(self.TOP + 7 * (self.CELL + self.GAP))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.resized.emit()

    def set_days(self, days):
        self.days = days
        vals = sorted(v for v in days.values() if v > 0)
        if vals:
            q = lambda f: vals[min(len(vals) - 1, int(len(vals) * f))]  # noqa: E731
            self.thresholds = (q(0.4), q(0.7), q(0.9))
        self.update()

    def weeks(self):
        return max(1, (self.width() - self.LEFT + self.GAP) // (self.CELL + self.GAP))

    def end_week_start(self):
        today = dt.date.today()
        sunday = today - dt.timedelta(days=(today.weekday() + 1) % 7)
        return sunday - dt.timedelta(weeks=self.offset_weeks)

    def first_day(self):
        return self.end_week_start() - dt.timedelta(weeks=self.weeks() - 1)

    def level(self, words):
        if words <= 0:
            return "zero"
        a, b, c = self.thresholds
        return 1 if words < a else 2 if words < b else 3 if words < c else 4

    def cell_rect(self, col, row):
        return QRectF(self.LEFT + col * (self.CELL + self.GAP), self.TOP + row * (self.CELL + self.GAP),
                      self.CELL, self.CELL)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        today = dt.date.today()
        start = self.first_day()
        weeks = self.weeks()
        p.setFont(theme.ui_font(12))
        p.setPen(QColor(theme.SAND[950]))
        for row, name in enumerate(("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")):
            r = self.cell_rect(0, row)
            p.drawText(QRectF(0, r.y(), self.LEFT - 8, r.height()),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)
        # month labels: above the week holding the 1st; the first column gets its month if there's room
        labels = []
        for col in range(weeks):
            week = start + dt.timedelta(weeks=col)
            first = next((week + dt.timedelta(days=i) for i in range(7)
                          if (week + dt.timedelta(days=i)).day == 1), None)
            if first:
                labels.append((col, first))
        if not labels or labels[0][0] >= 2:
            labels.insert(0, (0, start))
        p.setPen(QColor(theme.SAND[950]))
        for col, day in labels:
            if col < weeks - 1:
                p.drawText(QRectF(self.cell_rect(col, 0).x(), 0, 60, self.TOP - 8),
                           Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, day.strftime("%b"))
        for col in range(weeks):
            week = start + dt.timedelta(weeks=col)
            p.setPen(Qt.PenStyle.NoPen)
            for row in range(7):
                day = week + dt.timedelta(days=row)
                key = "future" if day > today else self.level(self.days.get(day, 0))
                p.setBrush(QColor(HEAT[key]))
                p.drawRoundedRect(self.cell_rect(col, row), 3, 3)

    def mouseMoveEvent(self, e):
        pos = e.position()
        col = int((pos.x() - self.LEFT) // (self.CELL + self.GAP))
        row = int((pos.y() - self.TOP) // (self.CELL + self.GAP))
        if 0 <= col < self.weeks() and 0 <= row < 7 and self.cell_rect(col, row).contains(pos):
            day = self.first_day() + dt.timedelta(weeks=col, days=row)
            words = self.days.get(day, 0)
            text = f"{day.strftime('%a, %b')} {day.day}: {words:,} word{'' if words == 1 else 's'}"
            QToolTip.showText(e.globalPosition().toPoint(), text, self)
        else:
            QToolTip.hideText()


class HourChart(QWidget):
    """24 small bars, one per hour of the day."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.counts = [0] * 24
        self.setFixedHeight(120)

    def set_counts(self, counts):
        self.counts = counts
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        top = max(self.counts) or 1
        peak = self.counts.index(max(self.counts)) if any(self.counts) else -1
        n = 24
        gap = 4
        w = (self.width() - gap * (n - 1)) / n
        base = self.height() - 22
        p.setFont(theme.ui_font(11))
        for h, c in enumerate(self.counts):
            x = h * (w + gap)
            hh = max(3, (base - 4) * c / top)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(theme.TEAL["dark"] if h == peak else theme.TEAL["light"] if c else theme.SECONDARY))
            p.drawRoundedRect(QRectF(x, base - hh, w, hh), 2, 2)
            if h % 6 == 0:
                p.setPen(QColor(theme.SAND[950]))
                p.drawText(QRectF(x, base + 4, w + 40, 16), Qt.AlignmentFlag.AlignLeft, _hour_text(h))


def _hour_text(h):
    return f"{h % 12 or 12}{'am' if h < 12 else 'pm'}"


class _Signals(QObject):
    voice_ready = Signal(object)


# ----------------------------------------------------------------------------- page
class InsightsPage(QWidget):
    MAX_WIDTH = 1100

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.sig = _Signals()
        self.sig.voice_ready.connect(self._show_voice)
        self.voice_dirty = True
        self.voice_busy = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(widgets.PageHeader("Insights"))
        root.addSpacing(26)
        self.tabs = widgets.TabBar(["Your usage", "Your voice"])
        root.addWidget(self.tabs)
        root.addSpacing(36)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)
        self.tabs.changed.connect(self._tab_changed)

        self.usage = QWidget()
        self._build_usage(self.usage)
        self.stack.addWidget(self.usage)
        self.voice = QWidget()
        self._build_voice(self.voice)
        self.stack.addWidget(self.voice)

        ctx.bus.history_changed.connect(self._on_history_changed)
        ctx.bus.dictionary_changed.connect(self._on_history_changed)

    # ------------------------------------------------------------------ build: usage
    def _build_usage(self, host):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(24)
        top = QHBoxLayout()
        top.setSpacing(24)
        lay.addLayout(top)

        # speed
        c = _card()
        self.wpm_num = _big_number("0")
        c.lay.addWidget(self.wpm_num)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(_caps_label("Words per minute"))
        self.wpm_info = _info("")
        row.addWidget(self.wpm_info)
        row.addStretch(1)
        c.lay.addLayout(row)
        c.lay.addSpacing(10)
        self.gauge = Gauge()
        c.lay.addWidget(self.gauge, 0, Qt.AlignmentFlag.AlignLeft)
        c.lay.addStretch(1)
        top.addWidget(c, 10)

        # fixes
        c = _card()
        self.fix_num = _big_number("0")
        c.lay.addWidget(self.fix_num)
        c.lay.addWidget(_caps_label("Fixes made by FlowLite"))
        c.lay.addSpacing(16)
        c.lay.addWidget(widgets.hline())
        c.lay.addSpacing(16)
        self.fix_rows = []
        for tip in ("Times you corrected a dictation afterwards and FlowLite noticed the edit.",
                    "Words your dictionary spelled or replaced for you automatically."):
            r = QHBoxLayout()
            lb = widgets.label("", 17)
            r.addWidget(lb)
            r.addStretch(1)
            r.addWidget(_info(tip, 17))
            c.lay.addLayout(r)
            c.lay.addSpacing(6)
            self.fix_rows.append(lb)
        c.lay.addStretch(1)
        top.addWidget(c, 10)

        # total words
        c = _card()
        head = QHBoxLayout()
        self.total_num = _big_number("0")
        head.addWidget(self.total_num)
        head.addStretch(1)
        self.trend = QFrame()
        self.trend.setObjectName("TrendPill")
        self.trend.setStyleSheet(f"#TrendPill {{ background: {theme.CARD}; border-radius: 8px; }}")
        tl = QHBoxLayout(self.trend)
        tl.setContentsMargins(10, 5, 12, 5)
        tl.setSpacing(6)
        self.trend_icon = QLabel()
        self.trend_icon.setStyleSheet("background: transparent;")
        tl.addWidget(self.trend_icon)
        self.trend_text = widgets.label("", 14, QFont.Weight.Medium)
        tl.addWidget(self.trend_text)
        self.trend.setToolTip("Words dictated in the last 30 days compared with the 30 days before.")
        head.addWidget(self.trend, 0, Qt.AlignmentFlag.AlignTop)
        c.lay.addLayout(head)
        c.lay.addWidget(_caps_label("Total words dictated"))
        c.lay.addSpacing(16)
        c.lay.addWidget(widgets.hline())
        c.lay.addSpacing(16)
        self.compare = widgets.label("", 17, wrap=True)
        c.lay.addWidget(self.compare)
        c.lay.addSpacing(12)
        bar = QFrame()
        bar.setObjectName("DesktopBar")
        bar.setFixedHeight(26)
        bar.setStyleSheet(f"#DesktopBar {{ background: {theme.TEAL['dark']}; border-radius: 4px; }}")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(10, 0, 10, 0)
        bl.setSpacing(6)
        ic = QLabel()
        ic.setPixmap(icons.pixmap("monitor", 15, "#ffffff", 1.8))
        ic.setStyleSheet("background: transparent;")
        bl.addWidget(ic)
        bl.addWidget(widgets.label("Desktop", 14, QFont.Weight.Medium, "#ffffff"))
        bl.addStretch(1)
        bl.addWidget(widgets.label("100%", 14, QFont.Weight.Medium, "#ffffff"))
        bar.setToolTip("FlowLite runs on this computer only.")
        c.lay.addWidget(bar)
        c.lay.addStretch(1)
        top.addWidget(c, 21)

        bottom = QHBoxLayout()
        bottom.setSpacing(24)
        lay.addLayout(bottom)

        # desktop usage
        c = _card(24)
        head = QHBoxLayout()
        head.addWidget(widgets.label("Desktop usage", 30, QFont.Weight.Medium))
        head.addStretch(1)
        self.apps_label = _caps_label("Total apps used | 0", 14, theme.FOREGROUND, QFont.Weight.DemiBold)
        head.addWidget(self.apps_label, 0, Qt.AlignmentFlag.AlignVCenter)
        c.lay.addLayout(head)
        c.lay.addSpacing(18)
        self.usage_rows = QVBoxLayout()
        self.usage_rows.setSpacing(12)
        c.lay.addLayout(self.usage_rows)
        c.lay.addStretch(1)
        bottom.addWidget(c, 45)

        # streak
        c = _card(24)
        head = QHBoxLayout()
        self.streak_title = widgets.label("0 day streak", 30, QFont.Weight.Medium)
        head.addWidget(self.streak_title)
        head.addStretch(1)
        self.longest_label = _caps_label("Longest streak | 0 days", 14, theme.FOREGROUND, QFont.Weight.DemiBold)
        head.addWidget(self.longest_label, 0, Qt.AlignmentFlag.AlignVCenter)
        c.lay.addLayout(head)
        c.lay.addSpacing(14)
        nav = QHBoxLayout()
        nav.setSpacing(4)
        self.prev_btn = widgets.IconButton("chevron_left", "Earlier", 16, 26, theme.SAND[950])
        self.next_btn = widgets.IconButton("chevron_right", "Later", 16, 26, theme.SAND[950])
        self.range_label = widgets.label("", 13, color=theme.SAND[950])
        nav.addWidget(self.prev_btn)
        nav.addWidget(self.range_label)
        nav.addStretch(1)
        nav.addWidget(self.next_btn)
        c.lay.addLayout(nav)
        self.heat = Heatmap()
        self.heat.resized.connect(self._update_range)
        c.lay.addWidget(self.heat)
        self.prev_btn.clicked.connect(lambda: self._page_heat(4))
        self.next_btn.clicked.connect(lambda: self._page_heat(-4))
        c.lay.addSpacing(14)
        legend = QHBoxLayout()
        legend.setSpacing(8)
        legend.addWidget(widgets.label("More", 14, color=theme.SAND[950]))
        for lvl in (4, 3, 2, 1):
            sw = QFrame()
            sw.setFixedSize(18, 18)
            sw.setStyleSheet(f"background: {HEAT[lvl]}; border-radius: 3px;")
            legend.addWidget(sw)
        legend.addWidget(widgets.label("Less", 14, color=theme.SAND[950]))
        legend.addStretch(1)
        c.lay.addLayout(legend)
        bottom.addWidget(c, 55)
        lay.addStretch(1)

    def _page_heat(self, weeks):
        self.heat.offset_weeks = max(0, self.heat.offset_weeks + weeks)
        self.next_btn.setEnabled(self.heat.offset_weeks > 0)
        self._update_range()
        self.heat.update()

    def _update_range(self):
        first = self.heat.first_day()
        last = min(dt.date.today(), self.heat.end_week_start() + dt.timedelta(days=6))
        self.range_label.setText(f"{first.strftime('%b')} {first.day} – {last.strftime('%b')} {last.day},"
                                 f" {last.year}")

    # ------------------------------------------------------------------ build: voice
    def _build_voice(self, host):
        lay = QVBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(24)
        intro = widgets.label("Worked out on this computer from your own dictations. Nothing is uploaded.",
                              15, color=theme.SAND[950], wrap=True)
        lay.addWidget(intro)
        self.voice_status = widgets.label("Reading your history…", 15, color=theme.FOREGROUND_TERTIARY)
        lay.addWidget(self.voice_status)
        self.voice_empty = widgets.EmptyState("insights", "Your voice profile is still forming",
                                              "Dictate a few more times and this page fills in with your "
                                              "favourite words, busiest hours and languages.")
        self.voice_empty.hide()
        lay.addWidget(self.voice_empty)

        self.voice_grid = QWidget()
        grid = QGridLayout(self.voice_grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(24)
        grid.setColumnStretch(0, 58)
        grid.setColumnStretch(1, 42)
        lay.addWidget(self.voice_grid)

        def titled(title, sub):
            c = _card(24)
            c.lay.setSpacing(4)
            c.lay.addWidget(widgets.label(title, 24, QFont.Weight.Medium))
            c.lay.addWidget(_caps_label(sub, 12))
            c.lay.addSpacing(14)
            return c

        c = titled("Words you say most", "Leaving out filler words")
        self.words_wrap = QVBoxLayout()
        self.words_wrap.setSpacing(10)
        c.lay.addLayout(self.words_wrap)
        c.lay.addStretch(1)
        grid.addWidget(c, 0, 0)

        c = titled("How you dictate", "Per dictation")
        self.length_rows = QVBoxLayout()
        self.length_rows.setSpacing(14)
        c.lay.addLayout(self.length_rows)
        c.lay.addStretch(1)
        grid.addWidget(c, 0, 1)

        c = titled("When you talk", "Dictations by hour of day")
        self.peak_label = widgets.label("", 17, wrap=True)
        c.lay.addWidget(self.peak_label)
        c.lay.addSpacing(12)
        self.hours = HourChart()
        c.lay.addWidget(self.hours)
        grid.addWidget(c, 1, 0)

        c = titled("Languages", "Detected while dictating")
        self.lang_rows = QVBoxLayout()
        self.lang_rows.setSpacing(16)
        c.lay.addLayout(self.lang_rows)
        c.lay.addStretch(1)
        grid.addWidget(c, 1, 1)

        c = titled("Words FlowLite learned", "From your corrections")
        self.learned_rows = QVBoxLayout()
        self.learned_rows.setSpacing(10)
        c.lay.addLayout(self.learned_rows)
        grid.addWidget(c, 2, 0, 1, 2)
        self.voice_grid.hide()
        lay.addStretch(1)

    # ------------------------------------------------------------------ refresh
    def refresh(self):
        global _REQUESTED_TAB
        if _REQUESTED_TAB in TAB_KEYS:
            self.tabs.select(TAB_KEYS.index(_REQUESTED_TAB), emit=False)
            self.stack.setCurrentIndex(TAB_KEYS.index(_REQUESTED_TAB))
            _REQUESTED_TAB = None
        self._refresh_usage()
        if self.stack.currentIndex() == 1:
            self._refresh_voice()

    def _tab_changed(self, idx):
        self.stack.setCurrentIndex(idx)
        if idx == 1:
            self._refresh_voice()

    def _on_history_changed(self):
        self.voice_dirty = True
        if self.isVisible():
            self.refresh()

    def _refresh_usage(self):
        h, db = self.ctx.history, self.ctx.db
        st = h.stats()
        wpm = st["wpm"]
        self.wpm_num.setText(f"{wpm:,}")
        top, line = speed_rank(wpm)
        self.wpm_info.setToolTip(f"Average over your last 100 dictations. {line}")
        self.gauge.set_value(wpm / 120 if wpm else 0, top)
        self.gauge.setToolTip(line)

        fixes = st["dictionary_fixes"] + st["words_corrected"]
        self.fix_num.setText(f"{fixes:,}")
        self.fix_rows[0].setText(f"{st['words_corrected']:,} words corrected")
        self.fix_rows[1].setText(f"{st['dictionary_fixes']:,} dictionary fixes")

        self.total_num.setText(f"{st['total_words']:,}")
        self.compare.setText(comparison_line(st["total_words"]))
        now = time.time()
        q = "select coalesce(sum(words),0) w from history where status='ok' and ts>=? and ts<?"
        recent = db.query(q, (now - 30 * 86400, now + 1))[0]["w"]
        before = db.query(q, (now - 60 * 86400, now - 30 * 86400))[0]["w"]
        if before:
            change = round((recent - before) * 100 / before)
            up = change >= 0
            self.trend_icon.setPixmap(icons.pixmap("trend_up" if up else "trend_down", 15,
                                                   theme.TEAL["dark"] if up else theme.FOREGROUND, 2))
            self.trend_text.setText(f"{abs(change):,}% this month")
            self.trend.show()
        elif recent:
            self.trend_icon.setPixmap(icons.pixmap("trend_up", 15, theme.TEAL["dark"], 2))
            self.trend_text.setText("New this month")
            self.trend.show()
        else:
            self.trend.hide()

        self._fill_usage(st["apps"])
        days = h.words_per_day(since_days=800)
        self.heat.set_days(days)
        cur, longest = st["day_streak"], st["longest_streak"]
        self.streak_title.setText(f"{cur:,} day streak")
        self.longest_label.setText(f"LONGEST STREAK | {longest:,} DAY{'' if longest == 1 else 'S'}")
        self.next_btn.setEnabled(self.heat.offset_weeks > 0)
        self._update_range()

    def _fill_usage(self, apps):
        _clear(self.usage_rows)
        self.apps_label.setText(f"TOTAL APPS USED | {apps:,}")
        rows = self.ctx.db.query("select category, count(*) n from history where status='ok' and"
                                 " mode='dictation' group by category")
        counts = collections.Counter()
        for r in rows:
            app_type, _, style = (r["category"] or "other/other").partition("/")
            if app_type in ("ai", "terminal"):
                counts["ai"] += r["n"]
            elif app_type == "document":
                counts["document"] += r["n"]
            elif app_type == "email":
                counts["email"] += r["n"]
            elif app_type == "messaging":
                counts["work" if style == "work" else "personal"] += r["n"]
            else:
                counts["other"] += r["n"]
        spec = [("ai", "bot", "AI prompt", "AI prompts"), ("document", "file", "document", "documents"),
                ("other", "infinity", "other task", "other tasks"),
                ("personal", "chat", "personal message", "personal messages"),
                ("email", "mail", "email", "emails"), ("work", "work", "work message", "work messages")]
        total = sum(counts.values())
        ordered = sorted(spec, key=lambda s: -counts[s[0]])
        for rank, (key, icon_name, one, many) in enumerate(ordered):
            n = counts[key]
            pct = round(n * 100 / total) if total else 0
            color = (theme.TEAL["dark"] if rank == 0 and n else theme.TEAL["mid"] if rank < 3 and n
                     else theme.TEAL["light"])
            row = QHBoxLayout()
            row.setSpacing(16)
            ic = QLabel()
            ic.setPixmap(icons.pixmap(icon_name, 22, theme.FOREGROUND, 1.7))
            ic.setFixedWidth(26)
            ic.setStyleSheet("background: transparent;")
            row.addWidget(ic)
            row.addWidget(PctBar(pct, color, 300))
            row.addSpacing(2)
            row.addWidget(_caps_label(f"{n:,} {one if n == 1 else many}", 14, theme.FOREGROUND,
                                      QFont.Weight.DemiBold, 1.5))
            row.addStretch(1)
            self.usage_rows.addLayout(row)

    # ------------------------------------------------------------------ voice profile
    def _refresh_voice(self):
        if not self.voice_dirty or self.voice_busy:
            return
        self.voice_busy = True
        self.voice_dirty = False
        self.voice_status.setText("Reading your history…")
        self.voice_status.show()
        db = self.ctx.db

        def work():
            try:
                result = analyze_voice(db)
            except Exception as e:  # noqa: BLE001
                result = {"error": str(e)}
            self.sig.voice_ready.emit(result)
        threading.Thread(target=work, daemon=True, name="insights-voice").start()

    def _show_voice(self, data):
        self.voice_busy = False
        if data.get("error"):
            self.voice_status.setText("Couldn't read your history right now.")
            return
        self.voice_status.hide()
        if not data["count"]:
            self.voice_grid.hide()
            self.voice_empty.show()
            return
        self.voice_empty.hide()
        self.voice_grid.show()

        _clear(self.words_wrap)
        words = data["top_words"]
        if words:
            peak = words[0][1]
            for word, n in words[:8]:
                row = QHBoxLayout()
                row.setSpacing(12)
                lb = widgets.label(word, 16, QFont.Weight.Medium)
                lb.setFixedWidth(150)
                lb.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                row.addWidget(lb)
                bar = _Bar(n / peak, theme.TEAL["light"])
                row.addWidget(bar, 1)
                cnt = widgets.label(f"{n:,}×", 14, color=theme.SAND[950])
                cnt.setFixedWidth(52)
                cnt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                row.addWidget(cnt)
                self.words_wrap.addLayout(row)
        else:
            self.words_wrap.addWidget(widgets.label("Not enough text yet.", 15, color=theme.SAND[950]))

        _clear(self.length_rows)
        for num, unit in ((f"{data['avg_words']:,}", "words on average"),
                          (_seconds_text(data["avg_seconds"]), "of talking on average"),
                          (f"{data['longest']:,}", "words in your longest one"),
                          (f"{data['count']:,}", "dictations in total")):
            lb = QLabel()
            lb.setTextFormat(Qt.TextFormat.RichText)
            lb.setStyleSheet("background: transparent;")
            lb.setText(f'<span style="font-family: \'{theme.DISPLAY_FAMILY}\'; font-size: 32px;">{num}</span>'
                       f'&nbsp;&nbsp;<span style="font-size: 16px;">{unit}</span>')
            self.length_rows.addWidget(lb)

        hours = data["hours"]
        if any(hours):
            peak = hours.index(max(hours))
            self.peak_label.setText(f"You talk most around {_hour_text(peak)}"
                                    f" – {_part_of_day(peak)} is your time.")
        self.hours.set_counts(hours)

        _clear(self.lang_rows)
        langs = data["languages"]
        total = sum(n for _, n in langs) or 1
        for rank, (code, n) in enumerate(langs[:6]):
            pct = round(n * 100 / total)
            row = QVBoxLayout()
            row.setSpacing(6)
            head = QHBoxLayout()
            head.addWidget(widgets.label(LANG_NAMES.get(code, code.upper() if code else "Unknown"), 16,
                                         QFont.Weight.Medium))
            head.addStretch(1)
            head.addWidget(widgets.label(f"{pct}%", 15, color=theme.SAND[950]))
            row.addLayout(head)
            row.addWidget(_Bar(n / total, theme.TEAL["dark"] if rank == 0 else theme.TEAL["mid"]
                               if rank == 1 else theme.TEAL["light"], 10))
            self.lang_rows.addLayout(row)
        if not langs:
            self.lang_rows.addWidget(widgets.label("No language info yet.", 15, color=theme.SAND[950]))

        _clear(self.learned_rows)
        learned = data["learned"]
        if learned:
            flow = QGridLayout()
            flow.setHorizontalSpacing(12)
            flow.setVerticalSpacing(10)
            for i, (phrase, repl) in enumerate(learned[:12]):
                text = f"{repl}  ←  {phrase}" if repl and repl != phrase else phrase
                chip = widgets.label(text, 15, QFont.Weight.Medium)
                chip.setStyleSheet(f"background: {theme.CARD}; border: 1px solid {theme.SECONDARY};"
                                   f" border-radius: 8px; padding: 6px 12px;")
                flow.addWidget(chip, i // 3, i % 3)
            for col in range(3):
                flow.setColumnStretch(col, 1)
            self.learned_rows.addLayout(flow)
        else:
            self.learned_rows.addWidget(widgets.label(
                "Nothing yet. When you fix a word FlowLite got wrong, it remembers the spelling here.", 15,
                color=theme.SAND[950], wrap=True))


class _Bar(QWidget):
    def __init__(self, fraction, color, height=14, parent=None):
        super().__init__(parent)
        self.fraction, self.color = max(0.0, min(1.0, fraction)), color
        self.setFixedHeight(height)
        self.setMinimumWidth(40)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        r = QRectF(self.rect())
        p.setBrush(QColor(theme.SECONDARY))
        p.drawRoundedRect(r, 3, 3)
        p.setBrush(QColor(self.color))
        p.drawRoundedRect(QRectF(0, 0, max(r.height(), r.width() * self.fraction), r.height()), 3, 3)


def _clear(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().setParent(None)
            item.widget().deleteLater()
        elif item.layout():
            _clear(item.layout())


def _seconds_text(sec):
    if sec >= 60:
        return f"{int(sec // 60)}m {int(sec % 60)}s"
    return f"{sec:.0f}s"


def _part_of_day(h):
    if 5 <= h < 12:
        return "morning"
    if 12 <= h < 17:
        return "afternoon"
    if 17 <= h < 22:
        return "evening"
    return "late night"


def analyze_voice(db):
    """Runs in a worker thread: word counts, hours, languages, lengths, learned words."""
    rows = db.query("select ts, language, final_text, asr_text, words, coalesce(nullif(speech_ms,0), audio_ms) ms"
                    " from history where status='ok' and coalesce(final_text, asr_text, '') != ''")
    words = collections.Counter()
    hours = [0] * 24
    langs = collections.Counter()
    lengths, secs = [], []
    for r in rows:
        text = r["final_text"] or r["asr_text"] or ""
        for w in WORD_RE.findall(text.lower()):
            w = w.strip("'’-")
            if len(w) >= 3 and w not in STOPWORDS:
                words[w] += 1
        hours[dt.datetime.fromtimestamp(r["ts"]).hour] += 1
        if r["language"]:
            langs[r["language"]] += 1
        n = r["words"] or len(text.split())
        lengths.append(n)
        if r["ms"]:
            secs.append(r["ms"] / 1000)
    learned = [(d["phrase"], d["replacement"]) for d in db.query(
        "select phrase, replacement from dictionary where source='learned' and is_snippet=0"
        " order by used desc, modified desc limit 12")]
    return {"count": len(rows), "top_words": words.most_common(10), "hours": hours,
            "languages": langs.most_common(), "learned": learned,
            "avg_words": round(sum(lengths) / len(lengths)) if lengths else 0,
            "avg_seconds": sum(secs) / len(secs) if secs else 0,
            "longest": max(lengths) if lengths else 0}
