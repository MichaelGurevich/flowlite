"""Style page: per-category writing style (formal / casual / very casual) and the
Auto cleanup level (none / light / medium / high).

Category tabs show a banner with the kind of apps the style applies to (initial-letter
bubbles in neutral colours, no logos) and three selectable sample cards. The Auto cleanup
tab shows four level cards with the same sentence cleaned up at each level. Choices are
saved immediately.
"""

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from .. import theme, widgets

CATEGORIES = [  # settings key, tab label, banner wording, example apps (name, initial)
    ("personal", "Personal messages", "personal messengers",
     [("WhatsApp", "W"), ("Telegram", "T"), ("Discord", "D"), ("Signal", "S")]),
    ("work", "Work messages", "work messengers",
     [("Slack", "S"), ("Microsoft Teams", "T"), ("Zoom", "Z"), ("Mattermost", "M")]),
    ("email", "Email", "email", [("Gmail", "G"), ("Outlook", "O"), ("Thunderbird", "T"), ("Proton Mail", "P")]),
    ("other", "Other", "other apps", [("Notion", "N"), ("Word", "W"), ("Notepad", "N"), ("Obsidian", "O")]),
]
BUBBLE_COLORS = ["#2f6b5e", "#3d6a8f", "#5b5a9e", "#9a5468"]

STYLES = [  # key, title, subtitle, avatar colour
    ("formal", "Formal.", "Caps + Punctuation", "#ead3f5"),
    ("casual", "Casual", "Caps + Less punctuation", "#f4c2ec"),
    ("very_casual", "very casual", "No Caps + Less punctuation", "#7a1f3d"),
]

# one original sample message per category, written in the formal style; the casual
# variants are derived (fewer commas, no closing period; then all lowercase)
SAMPLES = {
    "personal": "Hey, are we still on for dinner tonight? I'll bring dessert.",
    "work": "Quick update, the slides are ready. Can you review them by 3?",
    "email": "Hi Sam, thanks for the notes. I'll send the new draft by Thursday.",
    "other": "Book the train tickets, and send the photos to Dana on Friday.",
}

CLEANUP = [  # key, name, description, sample
    ("none", "None", "Your words exactly as spoken, ums and all",
     "um so I think we should like push the launch to next week because uh the designs aren't done"),
    ("light", "Light", "Drops filler words and fixes small grammar slips",
     "So I think we should push the launch to next week, because the designs aren't done."),
    ("medium", "Medium", "Smooths out false starts and tightens wording",
     "We should push the launch to next week, since the designs aren't done."),
    ("high", "High", "Rewrites into polished, concise text",
     "Let's move the launch to next week; the designs aren't ready."),
]


def styled_sample(text, style):
    if style == "formal":
        return text
    casual = text.replace(",", "").rstrip(".")
    return casual.lower() if style == "very_casual" else casual


def _set_display_px(lb, px, color="#fcfcfb"):
    f = theme.display_font(px)
    f.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 96)
    lb.setFont(f)
    lb.setStyleSheet(f'color: {color}; background: transparent; font-family: "{theme.DISPLAY_FAMILY}";'
                     f" font-size: {px}px;")


def _compact_badges(tabbar):
    """Keep TabBar's "Beta" tag pill-sized instead of stretching to the full row height."""
    for lb in tabbar.findChildren(QLabel):
        if lb.text() == "Beta":
            lb.setFixedHeight(lb.fontMetrics().height() + 6 + 6)
            lb.setStyleSheet(lb.styleSheet() + " padding: 1px 8px; margin-top: 6px;")
            tabbar.layout().setAlignment(lb, Qt.AlignmentFlag.AlignTop)


# ----------------------------------------------------------------------------- banner
class AppBubbles(QWidget):
    """Overlapping circles with app initials and a trailing "+" (stand-ins for app logos)."""

    D, STEP = 50, 42

    def __init__(self, parent=None):
        super().__init__(parent)
        self.apps = []

    def set_apps(self, apps):
        self.apps = apps
        self.setFixedSize(self.STEP * len(apps) + self.D + 4, self.D + 4)
        names = ", ".join(name for name, _ in apps)
        self.setToolTip(f"{names} and similar apps")
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ring = QPen(QColor(255, 255, 255, 110), 2)
        font = theme.ui_font(19, QFont.Weight.DemiBold)
        p.setFont(font)
        for i, (_name, letter) in enumerate(self.apps):
            r = QRectF(2 + i * self.STEP, 2, self.D, self.D)
            p.setPen(ring)
            p.setBrush(QColor(BUBBLE_COLORS[i % len(BUBBLE_COLORS)]))
            p.drawEllipse(r)
            p.setPen(QColor("#ffffff"))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, letter)
        r = QRectF(2 + len(self.apps) * self.STEP, 2, self.D, self.D)
        p.setPen(ring)
        p.setBrush(QColor(255, 255, 255, 46))
        p.drawEllipse(r)
        p.setPen(QPen(QColor(255, 255, 255, 170), 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        c, h = r.center(), 9
        p.drawLine(c.x() - h, c.y(), c.x() + h, c.y())
        p.drawLine(c.x(), c.y() - h, c.x(), c.y() + h)


class Banner(widgets.Hero):
    """Non-closable hero with a smaller serif headline and an optional right-side widget."""

    def __init__(self, title, body, palette, side=None, height=148):
        super().__init__(title, body, palette, closable=False, height=height)
        _set_display_px(self.title, 32)
        self.side = side
        if side is not None:
            side.setParent(self)
        self.relayout()

    def relayout(self):
        right = 32 + (self.side.width() + 32 if self.side is not None else 0)
        self.layout().setContentsMargins(32, 30, right, 28)
        self._place_side()

    def _place_side(self):
        if self.side is not None:
            self.side.move(self.width() - self.side.width() - 40, (self.height() - self.side.height()) // 2)

    def resizeEvent(self, e):
        self._place_side()
        super().resizeEvent(e)


# ----------------------------------------------------------------------------- cards
class SelectCard(QWidget):
    """Clickable rounded card; painted border shows hover / selected state."""

    clicked = Signal()

    def __init__(self, selected_color, radius=10, parent=None):
        super().__init__(parent)
        self.selected_color = selected_color
        self.radius = radius
        self.selected = False
        self.hover = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_selected(self, on):
        self.selected = on
        self.update()

    def enterEvent(self, e):
        self.hover = True
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.hover = False
        self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.selected:
            pen = QPen(QColor(self.selected_color), 1.6)
        else:
            pen = QPen(QColor(theme.SAND[700] if self.hover else theme.SECONDARY), 1)
        p.setPen(pen)
        p.setBrush(QColor(theme.BACKGROUND))
        inset = pen.widthF() / 2
        p.drawRoundedRect(QRectF(self.rect()).adjusted(inset, inset, -inset, -inset), self.radius, self.radius)


class StyleCard(SelectCard):
    def __init__(self, title, subtitle, avatar_color):
        super().__init__(theme.PURPLE_BORDER, 10)
        self.setFixedHeight(350)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 18, 18, 0)
        lay.setSpacing(3)
        lay.addWidget(widgets.label(title, 17, QFont.Weight.Medium))
        lay.addWidget(widgets.label(subtitle, 17))
        lay.addStretch(1)
        self.bubble = widgets.label("", 16, wrap=True)
        self.bubble.setStyleSheet(f"background: {theme.PURPLE_TINT}; color: {theme.FOREGROUND};"
                                  " border-radius: 12px; border-bottom-right-radius: 3px; padding: 14px 13px;")
        lay.addWidget(self.bubble)
        lay.addSpacing(12)
        row = QHBoxLayout()
        row.addStretch(1)
        avatar = QLabel("J")
        avatar.setFixedSize(52, 52)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFont(theme.ui_font(20, QFont.Weight.DemiBold))
        avatar.setStyleSheet(f"background: {avatar_color}; color: #ffffff; border-radius: 26px;")
        row.addWidget(avatar)
        lay.addLayout(row)
        lay.addSpacing(64)

    def set_sample(self, text):
        self.bubble.setText(text)


class CleanupCard(SelectCard):
    def __init__(self, name, description, sample):
        super().__init__(theme.FOREGROUND, 12)
        self.setFixedHeight(360)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 14, 16)
        lay.setSpacing(6)
        lay.addWidget(widgets.display_label(name, 34))
        lay.addWidget(widgets.label(description, 16, color=theme.FOREGROUND_TERTIARY, wrap=True))
        lay.addStretch(1)
        bubble = widgets.label(sample, 14, wrap=True)
        f = bubble.font()
        f.setItalic(True)
        bubble.setFont(f)
        bubble.setStyleSheet(f"background: {theme.PURPLE_TINT}; color: {theme.FOREGROUND}; font-style: italic;"
                             " border-radius: 10px; padding: 12px 14px;")
        lay.addWidget(bubble)


# ----------------------------------------------------------------------------- page
class StylePage(QWidget):
    MAX_WIDTH = 800

    def __init__(self, ctx):
        super().__init__()
        # the shell's stack sets an unscoped "background: transparent"; restate the theme here
        self.setStyleSheet(theme.stylesheet())
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = widgets.PageHeader("Style")
        header.setMinimumHeight(44)
        root.addWidget(header)
        root.addSpacing(46)

        self.tabs = widgets.TabBar([c[1] for c in CATEGORIES] + ["Auto cleanup"], badges={"Auto cleanup": "Beta"})
        self.tabs.changed.connect(self._show_tab)
        root.addWidget(self.tabs)
        _compact_badges(self.tabs)
        root.addSpacing(30)

        # --- category view
        self.category_view = QWidget()
        cv = QVBoxLayout(self.category_view)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(24)
        self.bubbles = AppBubbles()
        self.bubbles.set_apps(CATEGORIES[0][3])
        self.banner = Banner("", "Style formatting currently applies to English dictation.", "lagoon",
                             side=self.bubbles)
        cv.addWidget(self.banner)
        row = QHBoxLayout()
        row.setSpacing(24)
        self.style_cards = {}
        for key, title, subtitle, avatar in STYLES:
            card = StyleCard(title, subtitle, avatar)
            card.clicked.connect(lambda k=key: self._pick_style(k))
            row.addWidget(card, 1)
            self.style_cards[key] = card
        cv.addLayout(row)
        root.addWidget(self.category_view)

        # --- auto cleanup view
        self.cleanup_view = QWidget()
        lv = QVBoxLayout(self.cleanup_view)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(24)
        banner = Banner("Auto cleanup applies to all your dictations",
                        "Pick how much FlowLite tidies up what you say, in every app.", "dusk", height=168)
        note = widgets.label("Your original words are always kept: on Home, hover a dictation and use"
                             " <b>Show original</b> to get them back.", 16, color="#f4f2ec", wrap=True)
        note.setTextFormat(Qt.TextFormat.RichText)
        banner.extra.addWidget(note)
        lv.addWidget(banner)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.cleanup_cards = {}
        for key, name, desc, sample in CLEANUP:
            card = CleanupCard(name, desc, sample)
            card.clicked.connect(lambda k=key: self._pick_cleanup(k))
            row.addWidget(card, 1)
            self.cleanup_cards[key] = card
        lv.addLayout(row)
        root.addWidget(self.cleanup_view)
        root.addStretch(1)

        ctx.bus.settings_changed.connect(self._sync)
        self._show_tab(0)

    # --- public
    def open_tab(self, key):
        """Select a tab by key: personal | work | email | other | cleanup (e.g. from Settings)."""
        keys = [c[0] for c in CATEGORIES] + ["cleanup"]
        if key in keys:
            self.tabs.select(keys.index(key))

    def refresh(self):
        self._sync()

    # --- internals
    def _category(self):
        idx = self.tabs.index
        return CATEGORIES[idx] if idx < len(CATEGORIES) else None

    def _show_tab(self, idx):
        cat = self._category()
        self.category_view.setVisible(cat is not None)
        self.cleanup_view.setVisible(cat is None)
        if cat is not None:
            key, _label, wording, apps = cat
            self.banner.title.setText(f"This style applies in {wording}")
            self.bubbles.set_apps(apps)
            self.banner.relayout()
            for style, card in self.style_cards.items():
                card.set_sample(styled_sample(SAMPLES[key], style))
        self._sync()

    def _sync(self):
        cat = self._category()
        if cat is not None:
            current = self.ctx.settings.styles.get(cat[0], "formal")
            for style, card in self.style_cards.items():
                card.set_selected(style == current)
        level = self.ctx.settings.cleanup_level
        for key, card in self.cleanup_cards.items():
            card.set_selected(key == level)

    def _pick_style(self, style):
        cat = self._category()
        if cat is None or self.ctx.settings.styles.get(cat[0]) == style:
            return
        self.ctx.settings.styles[cat[0]] = style
        self.ctx.save_settings()
        self._sync()

    def _pick_cleanup(self, level):
        if self.ctx.settings.cleanup_level == level:
            return
        self.ctx.settings.cleanup_level = level
        self.ctx.save_settings()
        self._sync()
