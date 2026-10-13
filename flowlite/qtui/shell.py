"""The FlowLite hub window: frameless, Wispr-style chrome.

Layout measured from Wispr Flow's hub (1350x850 default, 1140x750 min):
sand-500 chrome, a 62 px icon rail on the left with tooltips, a title bar with panel
toggle / bell / window buttons, and a rounded sand-50 canvas that hosts the pages.
"""

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow, QScrollArea, QSizePolicy,
                               QStackedWidget, QToolButton, QVBoxLayout, QWidget)

from . import icons, theme, widgets

NAV = [  # key, label, icon
    ("home", "Home", "mic"),
    ("insights", "Insights", "insights"),
    ("dictionary", "Dictionary", "dictionary"),
    ("snippets", "Snippets", "snippets"),
    ("style", "Style", "style"),
    ("transforms", "Transforms", "transforms"),
    ("scratchpad", "Scratchpad", "scratchpad"),
]
NAV_BOTTOM = [("settings", "Settings", "settings"), ("help", "Shortcuts & help", "help")]
EDGE = 6


class RailButton(QToolButton):
    def __init__(self, key, text, icon_name, expanded=False):
        super().__init__()
        self.key = key
        self.text_label = text
        self.icon_name = icon_name
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIcon(icons.icon(icon_name, 21, theme.FOREGROUND, 1.8))
        self.setIconSize(QSize(21, 21))
        self.setToolTip(text)
        self.set_expanded(expanded)
        self.setStyleSheet(f"QToolButton {{ background: transparent; border: none; border-radius: 8px;"
                           f" text-align: left; padding-left: 10px; font-size: 15px; }}"
                           f" QToolButton:hover {{ background: {theme.SECONDARY}; }}"
                           f" QToolButton:checked {{ background: {theme.SECONDARY}; }}")

    def set_expanded(self, expanded):
        if expanded:
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            self.setText("  " + self.text_label)
            self.setFixedSize(196, 40)
        else:
            self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            self.setText("")
            self.setFixedSize(44, 40)


class Canvas(QFrame):
    """Rounded page canvas."""

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(theme.SECONDARY), 1))
        p.setBrush(QColor(theme.BACKGROUND))
        p.drawRoundedRect(self.rect().adjusted(0, 0, -1, -1), 16, 16)


class PageScroller(QScrollArea):
    """Scrollable page area that centers the page at its preferred max width."""

    def __init__(self, page):
        super().__init__()
        self.page = page
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget()
        holder.setObjectName("PageHolder")
        holder.setStyleSheet("#PageHolder { background: transparent; }")
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(40, 44, 40, 40)
        lay.addStretch(1)
        page.setMaximumWidth(getattr(page, "MAX_WIDTH", 1000))
        page.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        col = QVBoxLayout()
        col.addWidget(page)
        col.addStretch(1)
        lay.addLayout(col, 100)
        lay.addStretch(1)
        self.setWidget(holder)


class HubWindow(QMainWindow):
    closed_to_tray = Signal()

    def __init__(self, ctx, pages):
        """pages: dict key -> QWidget page (with optional refresh())."""
        super().__init__()
        self.ctx = ctx
        self.setWindowTitle("FlowLite")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setMinimumSize(1140, 750)
        self.resize(1350, 850)
        self.setMouseTracking(True)
        self.expanded = False

        chrome = QWidget()
        chrome.setObjectName("Chrome")
        chrome.setMouseTracking(True)
        chrome.setStyleSheet(f"#Chrome {{ background: {theme.CHROME}; }}")
        self.setCentralWidget(chrome)
        root = QVBoxLayout(chrome)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- title bar
        self.titlebar = QWidget()
        self.titlebar.setFixedHeight(54)
        tb = QHBoxLayout(self.titlebar)
        tb.setContentsMargins(14, 8, 8, 4)
        tb.setSpacing(6)
        self.panel_btn = widgets.IconButton("panel", "Toggle sidebar", 20, 36)
        self.panel_btn.clicked.connect(self.toggle_rail)
        tb.addWidget(self.panel_btn)
        logo = QLabel()
        logo.setPixmap(icons.pixmap("logo", 22, theme.FOREGROUND, 1.8))
        logo.setToolTip("FlowLite — runs fully on this PC")
        tb.addWidget(logo)
        tb.addStretch(1)
        local = widgets.label("● Local · offline", 13, QFont.Weight.Medium, theme.RECORDING_FG)
        local.setToolTip("Speech and AI run on this computer. Network access is blocked.")
        tb.addWidget(local)
        tb.addSpacing(10)
        for name, tip, slot in (("minimize", "Minimize", self.showMinimized),
                                ("maximize", "Maximize", self.toggle_max),
                                ("close", "Close", self.close)):
            b = widgets.IconButton(name, "", 16, 44)
            b.clicked.connect(slot)
            if name == "close":
                b.setStyleSheet("QToolButton { background: transparent; border: none; border-radius: 6px; }"
                                " QToolButton:hover { background: #e81123; }")
            tb.addWidget(b)
        root.addWidget(self.titlebar)

        # --- body: rail + canvas
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 14, 14)
        body.setSpacing(0)
        root.addLayout(body, 1)

        self.rail = QWidget()
        rail = QVBoxLayout(self.rail)
        rail.setContentsMargins(9, 14, 9, 6)
        rail.setSpacing(0)
        self.rail_buttons = {}
        for key, text, icon_name in NAV:
            b = RailButton(key, text, icon_name)
            b.clicked.connect(lambda _=False, k=key: self.navigate(k))
            rail.addWidget(b)
            self.rail_buttons[key] = b
        rail.addStretch(1)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {theme.SECONDARY};")
        rail.addWidget(sep)
        rail.addSpacing(8)
        for key, text, icon_name in NAV_BOTTOM:
            b = RailButton(key, text, icon_name)
            b.setCheckable(False)
            b.clicked.connect(lambda _=False, k=key: self.bottom_action(k))
            rail.addWidget(b)
            self.rail_buttons[key] = b
        self.rail.setFixedWidth(62)
        body.addWidget(self.rail)

        self.canvas = Canvas()
        cl = QVBoxLayout(self.canvas)
        cl.setContentsMargins(1, 1, 1, 1)
        self.stack = QStackedWidget()
        self.stack.setObjectName("PageStack")
        self.stack.setStyleSheet("#PageStack { background: transparent; }")
        cl.addWidget(self.stack)
        body.addWidget(self.canvas, 1)

        self.pages = {}
        for key, page in pages.items():
            scroller = PageScroller(page)
            self.stack.addWidget(scroller)
            self.pages[key] = (page, scroller)
        self.toast = widgets.Toast(self.canvas)
        ctx.bus.toast.connect(self.toast.show_text)
        ctx.bus.navigate.connect(self.navigate)
        self.current = None
        self.navigate("home")

    # --- navigation
    def navigate(self, key):
        key, _, tab = key.partition(":")
        if key not in self.pages:
            return
        page, scroller = self.pages[key]
        self.stack.setCurrentWidget(scroller)
        for k, b in self.rail_buttons.items():
            if b.isCheckable():
                b.setChecked(k == key)
        self.current = key
        if hasattr(page, "refresh"):
            page.refresh()
        if tab and hasattr(page, "open_tab"):
            page.open_tab(tab)

    def bottom_action(self, key):
        if key == "settings":
            self.ctx.bus.open_settings.emit("general")
        elif key == "help":
            self.ctx.bus.open_settings.emit("shortcuts")

    def toggle_rail(self):
        self.expanded = not self.expanded
        self.rail.setFixedWidth(216 if self.expanded else 62)
        for b in self.rail_buttons.values():
            b.set_expanded(self.expanded)

    def toggle_max(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def show_and_raise(self):
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()

    # --- close hides to tray (FlowLite keeps running in the background, like Wispr)
    def closeEvent(self, e):
        e.ignore()
        self.hide()
        self.closed_to_tray.emit()

    # --- frameless move / resize
    def _edges(self, pos):
        r = self.rect()
        edges = Qt.Edge(0)
        if pos.x() <= EDGE:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= r.width() - EDGE:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= EDGE:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= r.height() - EDGE:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or self.isMaximized():
            return super().mousePressEvent(e)
        pos = e.position().toPoint()
        edges = self._edges(pos)
        if edges:
            self.windowHandle().startSystemResize(edges)
        elif pos.y() < self.titlebar.height():
            self.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        if e.position().toPoint().y() < self.titlebar.height():
            self.toggle_max()

    def mouseMoveEvent(self, e):
        edges = self._edges(e.position().toPoint())
        shapes = {Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor, Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
                  Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor, Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor}
        if edges in shapes:
            self.setCursor(shapes[edges])
        elif edges in (Qt.Edge.LeftEdge | Qt.Edge.TopEdge, Qt.Edge.RightEdge | Qt.Edge.BottomEdge):
            self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        elif edges:
            self.setCursor(Qt.CursorShape.SizeBDiagCursor)
        else:
            self.unsetCursor()
        super().mouseMoveEvent(e)
