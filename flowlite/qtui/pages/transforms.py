"""Transforms page: saved rewrite prompts, shortcut slots and "Auto apply after dictation".

Layout follows Wispr Flow's Transforms screen (header + Beta tag, banner, auto-apply row,
"My Transforms" grid of cards). All rewriting runs on the local model through
flowlite.transforms_engine, always on a worker thread.
"""

import threading

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from ... import transforms_engine as engine
from ...formatter import Formatter
from .. import icons, theme, widgets

SAMPLE_TEXT = ("so basically i think we should probably push the review to thursday because like half "
               "the team is out on wednesday and um we still need the numbers from finance before we "
               "can decide anything")

SLOT_LABELS = {"transform_1": "Transform 1", "transform_2": "Transform 2"}


# ----------------------------------------------------------------------------- async helpers
class _Job(QObject):
    done = Signal(object, object)   # result, error


def run_async(owner, fn, on_done):
    """Run blocking `fn()` on a daemon thread; call `on_done(result, error)` on the GUI thread.

    The job is parented to `owner`, so if the owner (a modal, a page) is destroyed first the
    callback is silently dropped.
    """
    job = _Job(owner)
    job.done.connect(on_done)
    job.done.connect(job.deleteLater)

    def work():
        try:
            result, error = fn(), None
        except Exception as e:  # reported to the UI, never raised on the worker thread
            result, error = None, e
        try:
            job.done.emit(result, error)
        except RuntimeError:    # owner already deleted
            pass

    threading.Thread(target=work, name="flowlite-transform", daemon=True).start()
    return job


def formatter_for(ctx):
    """The app's local formatter, or a fresh one for the configured model."""
    return ctx.formatter or Formatter(getattr(ctx.settings, "llm_model", "llama3.2:3b"))


def error_text(error):
    if isinstance(error, OSError):
        return engine.UNAVAILABLE_MESSAGE
    return f"Something went wrong: {error}"


class Spinner(QWidget):
    """Small rotating arc used for the "Working…" state."""

    def __init__(self, size=16, color=theme.FOREGROUND, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._angle = 0
        self._color = QColor(color)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def _tick(self):
        self._angle = (self._angle + 8) % 360
        self.update()

    def start(self):
        self.show()
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self.hide()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(2, 2, self.width() - 4, self.height() - 4)
        track = QColor(self._color)
        track.setAlpha(40)
        p.setPen(QPen(track, 2))
        p.drawEllipse(r)
        pen = QPen(self._color, 2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawArc(r, -self._angle * 16, 100 * 16)


def key_chips(shortcut, px=13, bg=theme.CARD):
    chips = widgets.KeyChips(shortcut, px=px)
    for chip in chips.findChildren(QLabel):
        chip.setStyleSheet(f"background: {bg}; color: {theme.FOREGROUND}; border: 1px solid {theme.SECONDARY};"
                           f" border-radius: 5px; padding: 2px 6px;")
    return chips


def make_modal(host, width):
    """widgets.Modal whose card re-asserts the theme: the Modal's selector-less dim background
    otherwise cascades into inputs and buttons inside the card."""
    m = widgets.Modal(host, width)
    m.card.setStyleSheet(m.card.styleSheet() + theme.stylesheet())
    return m


def themed(modal):
    """Apply make_modal's fix to an existing modal (e.g. the one widgets.confirm returns)."""
    modal.card.setStyleSheet(modal.card.styleSheet() + theme.stylesheet())
    return modal


def field_label(text):
    return widgets.label(text, 14, QFont.Weight.Medium, theme.SAND[950])


def _plain_edit(placeholder="", height=120):
    ed = QPlainTextEdit()
    ed.setPlaceholderText(placeholder)
    ed.setFixedHeight(height)
    ed.setFont(theme.ui_font(15))
    return ed


# ----------------------------------------------------------------------------- banner
class TransformsHero(widgets.Hero):
    """Ember banner with original painted bubbles (generic line icons, no app logos)."""

    BUBBLES = [  # (offset from right edge, y, icon, tint)
        (141, 20, "chat", "#d98b5f"), (46, 20, "file", "#30302f"),
        (189, 101, "mail", "#8a6fc4"), (93, 101, "keyboard", "#e6c35c"), (0, 101, "globe", "#4f9a6a"),
        (235, 181, "bot", "#3d7fa8"), (141, 181, "work", "#c0504a"), (46, 181, "sparkle", "#2f6fb0"),
    ]

    def __init__(self):
        super().__init__("Transform works anywhere you write",
                         "Select text in any app and press a Transform shortcut to rewrite it locally.",
                         palette="ember", closable=False, height=200)
        self.layout().setContentsMargins(32, 30, 32, 28)
        self.title.setStyleSheet(self.title.styleSheet().replace("font-size: 40px", "font-size: 31px"))
        self.body.setMaximumWidth(360)
        self.title.setMaximumWidth(520)
        self._pix = {name: icons.pixmap(name, 22, "#ffffff", 2.0) for _, _, name, _ in self.BUBBLES}

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setClipRect(self.rect())
        for dx, y, name, tint in self.BUBBLES:
            cx, cy = self.width() - dx - 2, y + 4
            ring = QColor(255, 255, 255, 60)
            p.setPen(QPen(ring, 3))
            fill = QColor(tint)
            fill.setAlpha(225)
            p.setBrush(fill)
            p.drawEllipse(QPointF(cx, cy), 25, 25)
            p.drawPixmap(int(cx - 11), int(cy - 11), self._pix[name])


# ----------------------------------------------------------------------------- cards
class TransformCard(QFrame):
    clicked = Signal()

    def __init__(self, title, description, shortcut=None, create=False, parent=None):
        super().__init__(parent)
        self.setObjectName("TransformCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMinimumHeight(162)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._style(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 22)
        lay.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        if create:
            plus = QLabel()
            plus.setFixedSize(28, 28)
            plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
            plus.setPixmap(icons.pixmap("plus", 12, theme.FOREGROUND, 2.2))
            plus.setStyleSheet(f"background: {theme.SAND[500]}; border: 1px solid {theme.SECONDARY};"
                               f" border-radius: 14px;")
            top.addWidget(plus)
        elif shortcut:
            top.addWidget(key_chips(shortcut, 13, theme.SAND[300]))
        else:
            top.addWidget(widgets.label("No shortcut", 13, QFont.Weight.Medium, theme.SAND[800]))
        top.addStretch(1)
        holder = QWidget()
        holder.setFixedHeight(28)
        holder.setLayout(top)
        lay.addWidget(holder)
        lay.addSpacing(22)
        name = widgets.label(title, 17, QFont.Weight.Medium)
        lay.addWidget(name)
        lay.addSpacing(8)
        desc = widgets.label(description, 16, color=theme.FOREGROUND_TERTIARY, wrap=True)
        desc.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        lay.addWidget(desc)
        lay.addStretch(1)

    def _style(self, hover):
        border = theme.SAND[700] if hover else theme.SECONDARY
        self.setStyleSheet(f"#TransformCard {{ background: {theme.CARD}; border: 1px solid {border};"
                           f" border-radius: 16px; }}")

    def enterEvent(self, e):
        self._style(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._style(False)
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


# ----------------------------------------------------------------------------- page
class TransformsPage(QWidget):
    MAX_WIDTH = 800

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        # The shell's page holder sets a selector-less "background: transparent", which cascades over
        # the app sheet (Primary buttons, inputs). Re-assert the theme for this page's subtree.
        self.setStyleSheet(theme.stylesheet())
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # header
        self.header = widgets.PageHeader("Transforms", beta=True)
        self.pill = QFrame()
        self.pill.setObjectName("ShortcutPill")
        self.pill.setStyleSheet(f"#ShortcutPill {{ background: {theme.SAND[200]}; border: 1px solid {theme.SECONDARY};"
                                f" border-radius: 12px; }}")
        self.pill_lay = QHBoxLayout(self.pill)
        self.pill_lay.setContentsMargins(8, 6, 14, 6)
        self.pill_lay.setSpacing(8)
        self.header.add_right(self.pill)
        root.addWidget(self.header)
        root.addSpacing(26)

        # banner
        self.hero = TransformsHero()
        self.hero.add_button("Try it out", self.open_try)
        self.hero.add_button("How it works", self.open_how, light=False)
        root.addWidget(self.hero)
        root.addSpacing(26)

        # auto apply row
        auto = QHBoxLayout()
        auto.setSpacing(14)
        text = QVBoxLayout()
        text.setSpacing(4)
        text.addWidget(widgets.label("Auto apply after dictation", 16, QFont.Weight.Medium))
        text.addWidget(widgets.label("Run a transform on everything you dictate, automatically.", 14,
                                     color=theme.SAND[950]))
        auto.addLayout(text, 1)
        info = QLabel()
        info.setPixmap(icons.pixmap("info", 16, theme.SAND[800]))
        info.setToolTip("After each dictation, the chosen transform rewrites the text with the local "
                        "model before it is pasted. This adds a few seconds.")
        auto.addWidget(info, 0, Qt.AlignmentFlag.AlignVCenter)
        self.auto_combo = QComboBox()
        self.auto_combo.setFixedWidth(200)
        self.auto_combo.setStyleSheet(f"QComboBox:disabled {{ color: {theme.SAND[800]}; background: {theme.SAND[50]}; }}")
        self.auto_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.auto_combo.currentTextChanged.connect(self._auto_combo_changed)
        auto.addWidget(self.auto_combo, 0, Qt.AlignmentFlag.AlignVCenter)
        self.auto_toggle = widgets.Toggle(bool(ctx.settings.auto_transform))
        self.auto_toggle.toggled.connect(self._auto_toggled)
        auto.addWidget(self.auto_toggle, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addLayout(auto)
        root.addSpacing(30)

        # my transforms
        mine = QHBoxLayout()
        mine.setSpacing(12)
        mine.addWidget(widgets.display_label("My Transforms", 34))
        mine.addStretch(1)
        reset = widgets.button("  Reset to defaults", "Ghost", self.confirm_reset)
        reset.setIcon(icons.icon("refresh", 16, theme.FOREGROUND))
        reset.setIconSize(QSize(16, 16))
        reset.setFont(theme.ui_font(16, QFont.Weight.Medium))
        reset.setStyleSheet("padding: 8px 12px; font-size: 16px; font-weight: 500;")
        mine.addWidget(reset)
        self.create_btn = widgets.button("Create New", "Primary", lambda: self.open_editor(None))
        mine.addWidget(self.create_btn)
        root.addLayout(mine)
        root.addSpacing(18)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(16)
        for c in range(3):
            self.grid.setColumnStretch(c, 1)
        root.addLayout(self.grid)
        root.addStretch(1)

        ctx.bus.settings_changed.connect(self._on_settings_changed)
        self.refresh()

    # ------------------------------------------------------------------ data → widgets
    def refresh(self):
        self.transforms = engine.list_transforms(self.ctx.db)
        self._fill_pill()
        self._fill_auto()
        self._fill_grid()

    def _on_settings_changed(self):
        if not getattr(self, "_saving", False):
            self.refresh()

    def _fill_pill(self):
        while self.pill_lay.count():
            w = self.pill_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        t = engine.get_transform_for_slot(self.ctx.db, "transform_1")
        keys = self.ctx.settings.shortcuts.get("transform_1", "")
        if not t or not keys:
            self.pill.hide()
            return
        self.pill.show()
        self.pill_lay.addWidget(key_chips(keys, 14))
        verb = "to polish selected text" if t["name"].lower() == "polish" else f"to run {t['name']}"
        self.pill_lay.addWidget(widgets.label(verb, 16, QFont.Weight.Medium))

    def _fill_auto(self):
        current = self.ctx.settings.auto_transform or ""
        self.auto_combo.blockSignals(True)
        prev = self.auto_combo.currentText()
        self.auto_combo.clear()
        names = [t["name"] for t in self.transforms]
        self.auto_combo.addItems(names)
        pick = current if current in names else (prev if prev in names else "")
        if pick:
            self.auto_combo.setCurrentText(pick)
        self.auto_combo.blockSignals(False)
        on = bool(current) and current in names
        self.auto_toggle.blockSignals(True)
        if self.auto_toggle.isChecked() != on:
            self.auto_toggle.setChecked(on)
        self.auto_toggle.blockSignals(False)
        self.auto_toggle.setEnabled(bool(names))
        self.auto_combo.setEnabled(on)

    def _fill_grid(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w:
                w.deleteLater()
        cards = []
        for t in self.transforms:
            slot = t["shortcut_slot"]
            keys = self.ctx.settings.shortcuts.get(slot) if slot else None
            card = TransformCard(t["name"], t["description"] or "", keys)
            card.clicked.connect(lambda tid=t["id"]: self.open_editor(tid))
            cards.append(card)
        create = TransformCard("Create your own", "Write your own prompt", create=True)
        create.clicked.connect(lambda: self.open_editor(None))
        cards.append(create)
        for i, card in enumerate(cards):
            self.grid.addWidget(card, i // 3, i % 3)

    # ------------------------------------------------------------------ auto apply
    def _save_settings(self):
        self._saving = True
        try:
            self.ctx.save_settings()
        finally:
            self._saving = False

    def _auto_toggled(self, on):
        name = self.auto_combo.currentText() if on else ""
        self.auto_combo.setEnabled(on)
        if self.ctx.settings.auto_transform != name:
            self.ctx.settings.auto_transform = name
            self._save_settings()
            self.ctx.bus.toast.emit(f"{name} will run after each dictation" if on else "Auto apply turned off")

    def _auto_combo_changed(self, name):
        if self.auto_toggle.isChecked() and name and self.ctx.settings.auto_transform != name:
            self.ctx.settings.auto_transform = name
            self._save_settings()

    # ------------------------------------------------------------------ reset
    def confirm_reset(self):
        themed(widgets.confirm(self.window(), "Reset transforms?",
                        "This restores Polish and Prompt Engineer with their original prompts and "
                        "removes any transforms you created.", "Reset", self._reset, danger=True))

    def _reset(self):
        engine.reset_defaults(self.ctx.db)
        names = {t["name"] for t in engine.list_transforms(self.ctx.db)}
        if self.ctx.settings.auto_transform and self.ctx.settings.auto_transform not in names:
            self.ctx.settings.auto_transform = ""
            self._save_settings()
        self.refresh()
        self.ctx.bus.toast.emit("Transforms reset")

    # ------------------------------------------------------------------ editor modal
    def open_editor(self, transform_id):
        t = engine.get_transform(self.ctx.db, transform_id) if transform_id else None
        m = make_modal(self.window(), 580)
        m.body.setSpacing(10)
        m.body.addWidget(widgets.label("Edit transform" if t else "New transform", 20, QFont.Weight.DemiBold))
        m.body.addWidget(widgets.label("Transforms rewrite selected text with the local model, following "
                                       "your prompt.", 14, color=theme.SAND[950], wrap=True))
        m.body.addSpacing(4)

        m.body.addWidget(field_label("Name"))
        name = QLineEdit(t["name"] if t else "")
        name.setPlaceholderText("e.g. Friendly reply")
        name.setMaxLength(40)
        m.body.addWidget(name)

        m.body.addWidget(field_label("Description"))
        desc = QLineEdit((t["description"] or "") if t else "")
        desc.setPlaceholderText("A short note shown on the card")
        desc.setMaxLength(80)
        m.body.addWidget(desc)

        m.body.addWidget(field_label("Prompt"))
        prompt = _plain_edit("Describe how the text should be rewritten, e.g. \"Make this sound warm and "
                             "friendly, keep it short.\"", 150)
        prompt.setPlainText((t["prompt"] or "") if t else "")
        m.body.addWidget(prompt)

        m.body.addWidget(field_label("Shortcut"))
        slot = QComboBox()
        slot.addItem("None", None)
        for key in engine.SLOTS:
            keys = " + ".join(widgets.key_label(k) for k in self.ctx.settings.shortcuts.get(key, "").split("+") if k)
            owner = engine.get_transform_for_slot(self.ctx.db, key)
            suffix = ""
            if owner and (not t or owner["id"] != t["id"]):
                suffix = f"  (replaces {owner['name']})"
            slot.addItem(f"{keys}  ·  {SLOT_LABELS[key]}{suffix}", key)
        if t and t["shortcut_slot"] in engine.SLOTS:
            slot.setCurrentIndex(engine.SLOTS.index(t["shortcut_slot"]) + 1)
        m.body.addWidget(slot)

        err = widgets.label("", 13, color=theme.DANGER)
        err.hide()
        m.body.addWidget(err)
        m.body.addSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(10)
        if t and not t["builtin"]:
            delete = QPushButton("Delete")
            delete.setCursor(Qt.CursorShape.PointingHandCursor)
            delete.setStyleSheet(f"QPushButton {{ background: transparent; color: {theme.DANGER}; border: none;"
                                 f" border-radius: 8px; padding: 9px 14px; font-size: 15px; font-weight: 500; }}"
                                 f" QPushButton:hover {{ background: #fdecec; }}")
            delete.clicked.connect(lambda: (m.close_modal(), self._confirm_delete(t)))
            row.addWidget(delete)
        row.addStretch(1)
        row.addWidget(widgets.button("Cancel", "Secondary", m.close_modal))
        save = widgets.button("Save" if t else "Create", "Primary")
        row.addWidget(save)
        m.body.addLayout(row)

        def validate():
            save.setEnabled(bool(name.text().strip()) and bool(prompt.toPlainText().strip()))
        name.textChanged.connect(validate)
        prompt.textChanged.connect(validate)
        validate()

        def do_save():
            new_name = name.text().strip()
            clash = [x for x in engine.list_transforms(self.ctx.db)
                     if x["name"].lower() == new_name.lower() and (not t or x["id"] != t["id"])]
            if clash:
                err.setText("A transform with this name already exists.")
                err.show()
                m._place()
                return
            engine.save_transform(self.ctx.db, t["id"] if t else None, name=new_name,
                                  description=desc.text().strip(), prompt=prompt.toPlainText().strip(),
                                  shortcut_slot=slot.currentData())
            if t and self.ctx.settings.auto_transform == t["name"] and new_name != t["name"]:
                self.ctx.settings.auto_transform = new_name
                self._save_settings()
            m.close_modal()
            self.refresh()
            self.ctx.bus.toast.emit("Transform saved" if t else "Transform created")
        save.clicked.connect(do_save)
        name.returnPressed.connect(lambda: save.isEnabled() and do_save())
        m.open()
        name.setFocus()

    def _confirm_delete(self, t):
        def go():
            engine.delete_transform(self.ctx.db, t["id"])
            if self.ctx.settings.auto_transform == t["name"]:
                self.ctx.settings.auto_transform = ""
                self._save_settings()
            self.refresh()
            self.ctx.bus.toast.emit("Transform deleted")
        themed(widgets.confirm(self.window(), f"Delete {t['name']}?",
                               "This transform and its prompt will be removed.", "Delete", go, danger=True))

    # ------------------------------------------------------------------ try it out
    def open_try(self):
        transforms = engine.list_transforms(self.ctx.db)
        m = make_modal(self.window(), 640)
        m.body.setSpacing(10)
        m.body.addWidget(widgets.label("Try a transform", 20, QFont.Weight.DemiBold))
        model = getattr(formatter_for(self.ctx), "model", "")
        m.body.addWidget(widgets.label(f"Edit the sample, pick a transform and run it. Runs on this computer"
                                       f" with {model}.", 14, color=theme.SAND[950], wrap=True))
        m.body.addSpacing(4)

        pick_row = QHBoxLayout()
        pick_row.addWidget(field_label("Transform"))
        pick_row.addStretch(1)
        picker = QComboBox()
        picker.setFixedWidth(240)
        for t in transforms:
            picker.addItem(t["name"], t["prompt"])
        pick_row.addWidget(picker)
        m.body.addLayout(pick_row)

        m.body.addWidget(field_label("Your text"))
        source = _plain_edit("Type or paste some text…", 110)
        source.setPlainText(SAMPLE_TEXT)
        m.body.addWidget(source)

        m.body.addWidget(field_label("Result"))
        result = _plain_edit("The rewritten text will appear here.", 150)
        result.setReadOnly(True)
        result.setStyleSheet(f"QPlainTextEdit {{ background: {theme.SAND[200]}; border: 1px solid {theme.SECONDARY}; }}")
        m.body.addWidget(result)

        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        spin = Spinner(16)
        status_row.addWidget(spin)
        status = widgets.label("", 14, color=theme.SAND[950], wrap=True)
        status_row.addWidget(status, 1)
        m.body.addLayout(status_row)

        row = QHBoxLayout()
        row.setSpacing(10)
        copy_btn = widgets.button("Copy result", "Ghost")
        copy_btn.setIcon(icons.icon("copy", 16))
        copy_btn.setEnabled(False)
        row.addWidget(copy_btn)
        row.addStretch(1)
        row.addWidget(widgets.button("Close", "Secondary", m.close_modal))
        run = widgets.button("Run", "Primary")
        run.setMinimumWidth(110)
        row.addWidget(run)
        m.body.addLayout(row)

        def finished(text, error):
            try:
                spin.stop()
                run.setEnabled(True)
                run.setText("Run")
                if error is not None:
                    status.setStyleSheet(f"color: {theme.DANGER}; background: transparent;")
                    status.setText(error_text(error))
                    return
                result.setPlainText(text or "")
                copy_btn.setEnabled(bool(text))
                status.setStyleSheet(f"color: {theme.SAND[950]}; background: transparent;")
                status.setText(f"Done with {picker.currentText()}.")
            except RuntimeError:   # modal was closed meanwhile
                pass

        def go():
            text = source.toPlainText()
            if not text.strip() or not run.isEnabled() or picker.count() == 0:
                return
            prompt = picker.currentData()
            run.setEnabled(False)
            run.setText("Working…")
            copy_btn.setEnabled(False)
            spin.start()
            status.setStyleSheet(f"color: {theme.SAND[950]}; background: transparent;")
            status.setText("Rewriting with the local model…")
            fmt = formatter_for(self.ctx)
            run_async(m.card, lambda: engine.run_transform(fmt, prompt, text), finished)

        def copy():
            QGuiApplication.clipboard().setText(result.toPlainText())
            self.ctx.bus.toast.emit("Copied")
        run.clicked.connect(go)
        copy_btn.clicked.connect(copy)
        QShortcut(QKeySequence("Ctrl+Return"), m.card, go)
        m.open()

    # ------------------------------------------------------------------ how it works
    def open_how(self):
        m = make_modal(self.window(), 520)
        m.body.setSpacing(14)
        m.body.addWidget(widgets.display_label("How Transforms work", 30))
        keys1 = self.ctx.settings.shortcuts.get("transform_1", "win+alt+1")
        keys2 = self.ctx.settings.shortcuts.get("transform_2", "win+alt+2")
        pretty = lambda s: " + ".join(widgets.key_label(k) for k in s.split("+") if k)
        steps = [
            "Select some text in any app: an email, a chat, a document.",
            f"Press <b>{pretty(keys1)}</b> or <b>{pretty(keys2)}</b> for the transform on that shortcut.",
            "FlowLite copies the selection and rewrites it with the model on this computer.",
            "The result is pasted back over your selection. Press Ctrl + Z to undo.",
        ]
        for i, step in enumerate(steps, 1):
            row = QHBoxLayout()
            row.setSpacing(14)
            num = QLabel(str(i))
            num.setFixedSize(28, 28)
            num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            num.setFont(theme.ui_font(14, QFont.Weight.DemiBold))
            num.setStyleSheet(f"background: {theme.SAND[500]}; border: 1px solid {theme.SECONDARY};"
                              f" border-radius: 14px;")
            row.addWidget(num, 0, Qt.AlignmentFlag.AlignTop)
            text = widgets.label(step, 15, wrap=True)
            text.setTextFormat(Qt.TextFormat.RichText)
            text.setContentsMargins(0, 4, 0, 0)
            row.addWidget(text, 1)
            m.body.addLayout(row)
        note = QHBoxLayout()
        note.setSpacing(8)
        lock = QLabel()
        lock.setPixmap(icons.pixmap("lock", 15, theme.RECORDING_FG))
        lock.setStyleSheet("background: transparent;")
        note.addWidget(lock)
        note.addWidget(widgets.label("Your text never leaves this PC.", 14, QFont.Weight.Medium,
                                     theme.RECORDING_FG))
        note.addStretch(1)
        m.body.addSpacing(2)
        m.body.addLayout(note)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(widgets.button("Got it", "Primary", m.close_modal))
        m.body.addLayout(row)
        m.open()
