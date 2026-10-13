"""Dictionary and Snippets pages.

Both pages are views over the `dictionary` table (snippets are rows with is_snippet=1),
so they share one implementation (`_EntriesPage`): header + "Add new", underline tabs with
search / sort / refresh tools, a dismissible hero banner, and a hover list with star,
edit and delete actions. Each page brings its own hero and add/edit dialog.
"""

import json

from PySide6.QtCore import QPoint, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QMenu, QPlainTextEdit, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from ... import store
from .. import icons, theme, widgets

_STAR = "12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"
icons.PATHS.setdefault("star", f'<polygon points="{_STAR}"/>')
icons.PATHS.setdefault("star_filled", f'<polygon fill="CURRENT" points="{_STAR}"/>')
icons.PATHS.setdefault("pencil", '<path d="M21.17 6.81a1 1 0 0 0-3.99-3.99L3.84 16.17a2 2 0 0 0-.5.83l-1.32 4.35a.5.5 0 0'
                                 ' 0 .62.62l4.35-1.32a2 2 0 0 0 .83-.5z"/><path d="m15 5 4 4"/>')

SORTS = [("newest", "Newest first"), ("oldest", "Oldest first"), ("alpha", "Alphabetical (A-Z)"),
         ("starred", "Starred first")]
SNIPPET_LIMIT = 4000
TOOL_COLOR = theme.FOREGROUND_TERTIARY


# ----------------------------------------------------------------------------- small helpers
_ICON_CACHE = {}


def _icon(name, size=16, color=theme.FOREGROUND):
    key = (name, size, color)
    if key not in _ICON_CACHE:
        _ICON_CACHE[key] = icons.icon(name, size, color)
    return _ICON_CACHE[key]


def _pix(name, size=16, color=theme.FOREGROUND, stroke=1.8):
    lb = QLabel()
    lb.setPixmap(icons.pixmap(name, size, color, stroke))
    lb.setStyleSheet("background: transparent;")
    lb.setFixedSize(size, size)
    return lb


def _state_path():
    return store.DATA_DIR / "ui_state.json"


def _load_state():
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def hero_dismissed(key):
    """Hero banners the user closed are remembered in DATA_DIR/ui_state.json."""
    return key in _load_state().get("dismissed_heroes", [])


def dismiss_hero(key):
    state = _load_state()
    dismissed = state.setdefault("dismissed_heroes", [])
    if key not in dismissed:
        dismissed.append(key)
    try:
        store.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _state_path().write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError:
        pass


def _one_line(text):
    return " ".join((text or "").split())


class ElidedLabel(QLabel):
    """Single-line label that shrinks with "…" instead of forcing its full width."""

    def __init__(self, text, px=16, color=theme.FOREGROUND, weight=QFont.Weight.Normal, keep=48):
        super().__init__()
        self.keep = keep  # width it never shrinks below (when the text is at least that wide)
        self.full = _one_line(text)
        self.color = QColor(color)
        self.setFont(theme.ui_font(px, weight))
        self.setStyleSheet("background: transparent;")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        if len(self.full) > 70:
            self.setToolTip((text or "")[:600])

    def sizeHint(self):
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self.full) + 2, fm.height() + 4)

    def minimumSizeHint(self):
        fm = self.fontMetrics()
        return QSize(min(fm.horizontalAdvance(self.full) + 2, self.keep), fm.height() + 4)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setFont(self.font())
        p.setPen(self.color)
        text = self.fontMetrics().elidedText(self.full, Qt.TextElideMode.ElideRight, self.width())
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)


def _hero_chip(text, italic=False):
    chip = QLabel(text)
    f = theme.ui_font(16, QFont.Weight.Medium)
    f.setItalic(italic)
    chip.setFont(f)
    style = "font-style: italic;" if italic else ""
    chip.setStyleSheet("background: rgba(255,255,255,0.42); color: #2a2a2a; border-radius: 8px;"
                       f" padding: 8px 18px; {style}")
    return chip


def fix_modal(m, radius=12):
    """widgets.Modal sets an unscoped translucent background that cascades into the card's
    inputs and buttons; restating the theme on the card (closer ancestor) wins over it."""
    m.card.setStyleSheet(f"QWidget {{ background: transparent; }}"
                         f" #ModalCard {{ background: {theme.CARD}; border-radius: {radius}px; }}"
                         + theme.stylesheet())
    return m


def _field_label(text):
    return widgets.label(text, 14, QFont.Weight.Medium, theme.SAND[950])


def _error_label():
    lb = widgets.label("", 13, color=theme.DANGER, wrap=True)
    lb.hide()
    return lb


def _dialog_buttons(modal, ok_text, on_ok):
    row = QHBoxLayout()
    row.setSpacing(12)
    row.addStretch(1)
    row.addWidget(widgets.button("Cancel", "Secondary", modal.close_modal))
    ok = widgets.button(ok_text, "Primary", on_ok)
    ok.setEnabled(False)
    row.addWidget(ok)
    return row, ok


# ----------------------------------------------------------------------------- list row
class EntryRow(widgets.HoverRow):
    """One dictionary/snippet row; its hover actions are built on first hover."""

    def __init__(self, page, entry):
        super().__init__(min_height=53)
        self.page = page
        self.entry = entry
        self.lay.setContentsMargins(16, 8, 12, 8)
        self.lay.setSpacing(5)
        self.lay.addWidget(ElidedLabel(entry["phrase"], keep=320))
        if entry.get("replacement"):
            self.lay.addWidget(_pix("arrow", 13, theme.FOREGROUND, 2.0))
            self.lay.addWidget(ElidedLabel(entry["replacement"]))
        if entry.get("source") == "learned":
            sparkle = _pix("sparkle", 17, theme.ORANGE)
            sparkle.setToolTip("Learned from your edits")
            self.lay.addSpacing(4)
            self.lay.addWidget(sparkle)
        if entry.get("starred"):
            self.lay.addSpacing(2)
            self.lay.addWidget(_pix("star_filled", 14, theme.FOREGROUND))
        self.lay.addStretch(1)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.clicked.connect(lambda: page.open_editor(entry))

    def enterEvent(self, e):
        if self.actions is None:
            self.set_actions(self._build_actions())
        super().enterEvent(e)

    def _action(self, name, tip, slot):
        b = QToolButton()
        b.setIcon(_icon(name, 17, theme.FOREGROUND))
        b.setIconSize(QSize(17, 17))
        b.setFixedSize(32, 32)
        b.setToolTip(tip)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(f"QToolButton {{ background: transparent; border: none; border-radius: 8px; }}"
                        f" QToolButton:hover {{ background: {theme.SECONDARY}; }}")
        b.clicked.connect(slot)
        return b

    def _build_actions(self):
        box = QWidget()
        box.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        starred = bool(self.entry.get("starred"))
        lay.addWidget(self._action("star_filled" if starred else "star", "Unstar" if starred else "Star",
                                   lambda: self.page.toggle_star(self.entry)))
        lay.addWidget(self._action("pencil", "Edit", lambda: self.page.open_editor(self.entry)))
        lay.addWidget(self._action("trash", "Delete", lambda: self.page.delete_entry(self.entry)))
        return box


# ----------------------------------------------------------------------------- shared page
class _EntriesPage(QWidget):
    MAX_WIDTH = 800
    SNIPPETS = False
    TITLE = ""
    TABS = ["All"]
    HERO_KEY = ""
    PAGE_SIZE = 150

    def __init__(self, ctx):
        super().__init__()
        # the shell's stack sets an unscoped "background: transparent" that would also wipe the
        # theme's button/field backgrounds; restating the theme here takes precedence over it
        self.setStyleSheet(theme.stylesheet())
        self.ctx = ctx
        self.sort = "newest"
        self.limit = self.PAGE_SIZE
        self.hero = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = widgets.PageHeader(self.TITLE)
        header.setMinimumHeight(44)
        header.add_right(widgets.button("Add new", "Primary", lambda: self.open_editor()))
        root.addWidget(header)
        root.addSpacing(46)

        self.tabs = widgets.TabBar(self.TABS)
        self.tabs.changed.connect(self._reset_and_refresh)
        self.search_btn = self._tool("search", "Search")
        self.search_btn.setCheckable(True)
        self.search_btn.toggled.connect(self._toggle_search)
        self.sort_btn = self._tool("sort", "Sort")
        self.sort_btn.clicked.connect(self._sort_menu)
        refresh_btn = self._tool("refresh", "Refresh")
        refresh_btn.clicked.connect(self.refresh)
        for b in (self.search_btn, self.sort_btn, refresh_btn):
            self.tabs.add_tool(b)
        root.addWidget(self.tabs)

        self.search_box = QWidget()
        sl = QVBoxLayout(self.search_box)
        sl.setContentsMargins(0, 16, 0, 0)
        self.search = widgets.SearchField(self.SEARCH_PLACEHOLDER)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(150)
        self._search_timer.timeout.connect(self._reset_and_refresh)
        self.search.textChanged.connect(lambda _: self._search_timer.start())
        esc = QShortcut(QKeySequence("Escape"), self.search, activated=lambda: self.search_btn.setChecked(False))
        esc.setContext(Qt.ShortcutContext.WidgetShortcut)
        sl.addWidget(self.search)
        self.search_box.hide()
        root.addWidget(self.search_box)

        if not hero_dismissed(self.HERO_KEY):
            self.hero_box = QWidget()
            hl = QVBoxLayout(self.hero_box)
            hl.setContentsMargins(0, 26, 0, 0)
            self.hero = self.build_hero()
            self.hero.dismissed.connect(self._dismiss_hero)
            hl.addWidget(self.hero)
            root.addWidget(self.hero_box)

        root.addSpacing(36)
        self.list = widgets.ListCard()
        root.addWidget(self.list)
        self.empty_box = QVBoxLayout()
        root.addLayout(self.empty_box)
        self.empty = None
        self.more_btn = widgets.button("Show more", "Ghost", self._show_more)
        self.more_btn.setFont(theme.ui_font(15, QFont.Weight.Medium))
        root.addSpacing(8)
        root.addWidget(self.more_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        root.addStretch(1)

        ctx.bus.dictionary_changed.connect(self.refresh)
        self.refresh()

    # --- overridables
    SEARCH_PLACEHOLDER = "Search"

    def build_hero(self):
        raise NotImplementedError

    def update_hero(self, entries):
        pass

    def tab_filter(self, rows, tab):
        return rows

    def empty_state(self, tab):
        return "dictionary", "Nothing here yet", ""

    def open_editor(self, entry=None):
        raise NotImplementedError

    # --- toolbar
    def _tool(self, name, tip):
        return widgets.IconButton(name, tip, 18, 34, TOOL_COLOR)

    def _toggle_search(self, on):
        self.search_box.setVisible(on)
        if on:
            self.search.setFocus()
            return
        self._search_timer.stop()
        self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(False)
        self._reset_and_refresh()

    def _sort_menu(self):
        menu = QMenu(self)
        for key, text in SORTS:
            act = menu.addAction(("✓  " if key == self.sort else "     ") + text)
            act.triggered.connect(lambda _=False, k=key: self._set_sort(k))
        menu.exec(self.sort_btn.mapToGlobal(QPoint(self.sort_btn.width() - 200, self.sort_btn.height() + 4)))

    def _set_sort(self, key):
        self.sort = key
        self._reset_and_refresh()

    def _dismiss_hero(self):
        dismiss_hero(self.HERO_KEY)
        self.hero_box.hide()

    # --- data
    def _all_entries(self):
        return self.ctx.dictionary.entries(snippets=self.SNIPPETS, search="", sort="starred")

    def _reset_and_refresh(self, *_):
        self.limit = self.PAGE_SIZE
        self.refresh()

    def _show_more(self):
        self.limit += self.PAGE_SIZE
        self.refresh()

    def refresh(self):
        query = self.search.text().strip() if self.search_btn.isChecked() else ""
        rows = self.ctx.dictionary.entries(snippets=self.SNIPPETS, search=query, sort=self.sort)
        rows = self.tab_filter(rows, self.tabs.index)
        self.list.clear()
        for entry in rows[:self.limit]:
            self.list.add(EntryRow(self, entry))
        self.list.setVisible(bool(rows))
        self.more_btn.setVisible(len(rows) > self.limit)
        if self.empty is not None:
            self.empty.setParent(None)
            self.empty.deleteLater()
            self.empty = None
        if not rows:
            if query:
                icon_name, title, body = "search", "No matches", f"Nothing matches “{query}”."
            else:
                icon_name, title, body = self.empty_state(self.tabs.index)
            self.empty = widgets.EmptyState(icon_name, title, body)
            self.empty_box.addWidget(self.empty)
        if self.hero is not None:
            self.update_hero(self._all_entries())

    def _changed(self):
        # deferred so the row whose button fired is not rebuilt inside its own click handler
        QTimer.singleShot(0, self.ctx.bus.dictionary_changed.emit)

    # --- row actions
    def toggle_star(self, entry):
        self.ctx.dictionary.star(entry["id"], not entry.get("starred"))
        self._changed()

    def delete_entry(self, entry):
        what = "snippet" if self.SNIPPETS else "word"

        def go():
            self.ctx.dictionary.remove(entry["id"])
            self._changed()
            self.ctx.bus.toast.emit(f"{what.capitalize()} deleted")
        fix_modal(widgets.confirm(self.window(), f"Delete this {what}?",
                        f"“{_one_line(entry['phrase'])[:80]}” will be removed from your "
                        f"{'snippets' if self.SNIPPETS else 'dictionary'}.",
                        "Delete", go, danger=True))

    def _duplicate(self, phrase, entry_id):
        return bool(self.ctx.db.query(
            "select 1 from dictionary where is_snippet=? and lower(phrase)=lower(?) and id != ?",
            (1 if self.SNIPPETS else 0, phrase, entry_id or -1)))


# ----------------------------------------------------------------------------- Dictionary
class DictionaryPage(_EntriesPage):
    TITLE = "Dictionary"
    TABS = ["All", "Personal", "Learned"]
    HERO_KEY = "dictionary"
    SEARCH_PLACEHOLDER = "Search your dictionary"

    def build_hero(self):
        hero = widgets.Hero(
            "FlowLite spells the way <i>you</i> do.",
            "Fix a word once, or add it here yourself, and <b>names, product terms and in-house jargon</b>"
            " come out right every time you dictate.",
            palette="ember", height=218)
        hero.layout().setContentsMargins(32, 34, 72, 32)
        self._add_word_btn = hero.add_button("Add new word", lambda: self.open_editor())
        self._chips = []
        return hero

    def update_hero(self, entries):
        for chip in self._chips:
            chip.setParent(None)
            chip.deleteLater()
        self._chips = []
        seen = set()
        fm = QFontMetrics(theme.ui_font(16, QFont.Weight.Medium))
        m = self.hero.layout().contentsMargins()
        room = self.MAX_WIDTH - m.left() - m.right() - self._add_word_btn.sizeHint().width()
        for e in entries:
            word = _one_line(e["replacement"] or e["phrase"])
            if not word or len(word) > 22 or word.lower() in seen:
                continue
            need = fm.horizontalAdvance(word) + 36 + 10 + 8  # padding, spacing, fallback-font slack
            if need > room:
                continue
            room -= need
            seen.add(word.lower())
            self._chips.append(self.hero.add_chip(word, lambda _=False, ent=e: self.open_editor(ent)))
            if len(self._chips) == 5:
                break

    def tab_filter(self, rows, tab):
        if tab == 1:
            return [r for r in rows if r.get("source") != "learned"]
        if tab == 2:
            return [r for r in rows if r.get("source") == "learned"]
        return rows

    def empty_state(self, tab):
        if tab == 2:
            if self.ctx.settings.learn_from_edits:
                return ("sparkle", "Nothing learned yet",
                        "When you correct a word FlowLite got wrong, it shows up here on its own.")
            return ("sparkle", "Learning is turned off",
                    "Turn on Auto-add to dictionary in Settings → System.")
        return ("dictionary", "Your dictionary is empty",
                "Add names, product terms or jargon so FlowLite always spells them right.")

    def open_editor(self, entry=None):
        WordDialog(self, entry)


class WordDialog:
    """"Add to vocabulary" modal: a plain word, or misspelling -> correct spelling."""

    def __init__(self, page, entry=None):
        self.page, self.entry = page, entry
        self.m = m = fix_modal(widgets.Modal(page.window(), 480, padding=24))
        m.body.setSpacing(16)
        m.body.addWidget(widgets.label("Edit word" if entry else "Add to vocabulary", 20, QFont.Weight.DemiBold))

        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(widgets.label("Correct a misspelling", 15, QFont.Weight.Medium, theme.SAND[950]))
        info = _pix("info", 15, theme.FOREGROUND_TERTIARY)
        info.setToolTip("Use this when FlowLite keeps writing a word wrong:\n"
                        "whenever it hears the misspelling, it writes your spelling instead.")
        row.addWidget(info)
        row.addStretch(1)
        self.toggle = widgets.Toggle(bool(entry and entry.get("replacement")))
        row.addWidget(self.toggle)
        m.body.addLayout(row)

        self.word = QLineEdit()
        self.word.setPlaceholderText("Add a new word")
        m.body.addWidget(self.word)

        self.pair = QWidget()
        pl = QHBoxLayout(self.pair)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(10)
        self.wrong = QLineEdit()
        self.wrong.setPlaceholderText("Misspelling")
        self.right = QLineEdit()
        self.right.setPlaceholderText("Correct spelling")
        pl.addWidget(self.wrong, 1)
        pl.addWidget(_pix("arrow", 16, theme.FOREGROUND_TERTIARY, 2.0))
        pl.addWidget(self.right, 1)
        m.body.addWidget(self.pair)

        self.error = _error_label()
        m.body.addWidget(self.error)

        buttons, self.ok = _dialog_buttons(m, "Save" if entry else "Add word", self.submit)
        m.body.addSpacing(2)
        m.body.addLayout(buttons)

        if entry:
            if entry.get("replacement"):
                self.wrong.setText(entry["phrase"])
                self.right.setText(entry["replacement"])
            else:
                self.word.setText(entry["phrase"])
        for edit in (self.word, self.wrong, self.right):
            edit.textChanged.connect(self._update)
            edit.returnPressed.connect(self.submit)
        self.toggle.toggled.connect(self._mode_changed)
        self._mode_changed(self.toggle.isChecked(), place=False)
        m.open()
        QTimer.singleShot(0, self._focus)

    def _focus(self):
        (self.wrong if self.toggle.isChecked() else self.word).setFocus()

    def _mode_changed(self, correcting, place=True):
        # carry the typed text over when switching modes
        if correcting and self.word.text() and not self.wrong.text():
            self.wrong.setText(self.word.text())
        elif not correcting and self.wrong.text() and not self.word.text():
            self.word.setText(self.right.text() or self.wrong.text())
        self.word.setVisible(not correcting)
        self.pair.setVisible(correcting)
        self.error.hide()
        self._update()
        if place:
            self.m._place()
            self._focus()

    def _values(self):
        if self.toggle.isChecked():
            return self.wrong.text().strip(), self.right.text().strip()
        return self.word.text().strip(), None

    def _update(self):
        phrase, repl = self._values()
        self.ok.setEnabled(bool(phrase) and (repl is None or bool(repl)))
        if self.error.isVisible():
            self.error.hide()
            self.m._place()

    def _fail(self, text):
        self.error.setText(text)
        self.error.show()
        self.m._place()

    def submit(self):
        if not self.ok.isEnabled():
            return
        phrase, repl = self._values()
        if repl is not None and repl == phrase:
            return self._fail("The misspelling and the correct spelling are the same.")
        if self.page._duplicate(phrase, self.entry and self.entry["id"]):
            return self._fail("That's already in your dictionary.")
        d = self.page.ctx.dictionary
        if self.entry:
            d.update(self.entry["id"], phrase=phrase, replacement=repl)
            toast = "Saved"
        else:
            d.add(phrase, repl)
            toast = "Added to dictionary"
        self.m.close_modal()
        self.page._changed()
        self.page.ctx.bus.toast.emit(toast)


# ----------------------------------------------------------------------------- Snippets
SNIPPET_EXAMPLES = [  # generic examples for the hero
    ("my address", "221 Example Street, Springfield"),
    ("sign off", "Thanks so much, talk soon!"),
    ("bug template", "Steps to reproduce, expected result, actual result…"),
]


class SnippetsPage(_EntriesPage):
    TITLE = "Snippets"
    TABS = ["All", "Starred"]
    SNIPPETS = True
    HERO_KEY = "snippets"
    SEARCH_PLACEHOLDER = "Search your snippets"

    def build_hero(self):
        hero = widgets.Hero(
            "The stuff <i>you</i> shouldn’t have to re-type.",
            "Give a phrase you write again and again a short name. Say the name while dictating"
            " and FlowLite types the whole thing.",
            palette="plum")
        hero.layout().setContentsMargins(32, 34, 72, 34)
        hero.extra.setSpacing(8)
        hero.extra.setContentsMargins(0, 4, 0, 0)
        for trigger, expansion in SNIPPET_EXAMPLES:
            row = QHBoxLayout()
            row.setSpacing(10)
            row.addWidget(_hero_chip(f"“{trigger}”", italic=True))
            row.addWidget(_pix("arrow", 14, "#f4f2ec", 2.0))
            row.addWidget(_hero_chip(expansion))
            row.addStretch(1)
            hero.extra.addLayout(row)
        hero.add_button("Add new snippet", lambda: self.open_editor())
        return hero

    def tab_filter(self, rows, tab):
        return [r for r in rows if r.get("starred")] if tab == 1 else rows

    def empty_state(self, tab):
        if tab == 1:
            return ("star", "No starred snippets", "Star the snippets you use most to find them quickly.")
        return ("snippets", "No snippets yet",
                "Create one, then just say its name while dictating.")

    def open_editor(self, entry=None):
        SnippetDialog(self, entry)


class SnippetDialog:
    def __init__(self, page, entry=None):
        self.page, self.entry = page, entry
        self.m = m = fix_modal(widgets.Modal(page.window(), 560, padding=24))
        m.body.setSpacing(10)
        m.body.addWidget(widgets.label("Edit snippet" if entry else "Add snippet", 20, QFont.Weight.DemiBold))
        m.body.addSpacing(6)

        m.body.addWidget(_field_label("Snippet"))
        self.trigger = QLineEdit()
        self.trigger.setPlaceholderText("What you'll say, e.g. “my address”")
        m.body.addWidget(self.trigger)
        m.body.addSpacing(6)

        m.body.addWidget(_field_label("Expansion"))
        self.expansion = QPlainTextEdit()
        self.expansion.setPlaceholderText("The text FlowLite types when you say the snippet")
        self.expansion.setMinimumHeight(150)
        self.expansion.setTabChangesFocus(True)
        m.body.addWidget(self.expansion)
        self.counter = widgets.label("", 13, color=theme.FOREGROUND_TERTIARY)
        self.counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        m.body.addWidget(self.counter)

        self.error = _error_label()
        m.body.addWidget(self.error)
        buttons, self.ok = _dialog_buttons(m, "Save" if entry else "Add snippet", self.submit)
        m.body.addLayout(buttons)

        if entry:
            self.trigger.setText(entry["phrase"])
            self.expansion.setPlainText(entry.get("replacement") or "")
        self.trigger.textChanged.connect(self._update)
        self.trigger.returnPressed.connect(self.expansion.setFocus)
        self.expansion.textChanged.connect(self._expansion_changed)
        for seq in ("Ctrl+Return", "Ctrl+Enter"):
            QShortcut(QKeySequence(seq), m.card, activated=self.submit)
        self._expansion_changed()
        m.open()
        QTimer.singleShot(0, self.trigger.setFocus)

    def _expansion_changed(self):
        text = self.expansion.toPlainText()
        if len(text) > SNIPPET_LIMIT:
            cur = self.expansion.textCursor()
            pos = min(cur.position(), SNIPPET_LIMIT)
            self.expansion.blockSignals(True)
            self.expansion.setPlainText(text[:SNIPPET_LIMIT])
            self.expansion.blockSignals(False)
            cur = self.expansion.textCursor()
            cur.setPosition(pos)
            self.expansion.setTextCursor(cur)
            text = text[:SNIPPET_LIMIT]
        self.counter.setText(f"{len(text):,} / {SNIPPET_LIMIT:,}")
        self._update()

    def _update(self):
        self.ok.setEnabled(bool(self.trigger.text().strip()) and bool(self.expansion.toPlainText().strip()))
        if self.error.isVisible():
            self.error.hide()
            self.m._place()

    def submit(self):
        if not self.ok.isEnabled():
            return
        trigger = self.trigger.text().strip()
        expansion = self.expansion.toPlainText().strip()
        if self.page._duplicate(trigger, self.entry and self.entry["id"]):
            self.error.setText("You already have a snippet with that name.")
            self.error.show()
            self.m._place()
            return
        d = self.page.ctx.dictionary
        if self.entry:
            d.update(self.entry["id"], phrase=trigger, replacement=expansion)
            toast = "Snippet saved"
        else:
            d.add(trigger, expansion, snippet=True)
            toast = "Snippet added"
        self.m.close_modal()
        self.page._changed()
        self.page.ctx.bus.toast.emit(toast)
