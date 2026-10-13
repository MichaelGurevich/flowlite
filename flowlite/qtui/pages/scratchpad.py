"""Scratchpad: quick local notes you can dictate into (FlowLite pastes into the focused editor).

Notes list on the left (search, pinned first, hover pin/delete), a rich-text editor card on
the right with a small formatting toolbar, autosave 600 ms after the last edit, and an
optional Transform action that rewrites the selection (or the whole note) with the local model.
"""

import time

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QFont, QFontMetrics, QGuiApplication, QKeySequence, QTextCharFormat, QTextCursor,
                           QTextDocument, QTextListFormat)
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu, QScrollArea, QSizePolicy,
                               QTextEdit, QVBoxLayout, QWidget)

from ... import transforms_engine as engine
from .. import icons, theme, widgets
from .transforms import Spinner, error_text, formatter_for, run_async, themed

# Extra Lucide-style icons (ISC licence, see icons.py).
icons.PATHS.setdefault("bold", '<path d="M6 12h9a4 4 0 0 1 0 8H7a1 1 0 0 1-1-1V5a1 1 0 0 1 1-1h7a4 4 0 0 1 0 8"/>')
icons.PATHS.setdefault("italic", '<line x1="19" x2="10" y1="4" y2="4"/><line x1="14" x2="5" y1="20" y2="20"/>'
                                 '<line x1="15" x2="9" y1="4" y2="20"/>')
icons.PATHS.setdefault("list", '<path d="M3 12h.01"/><path d="M3 18h.01"/><path d="M3 6h.01"/><path d="M8 12h13"/>'
                               '<path d="M8 18h13"/><path d="M8 6h13"/>')
icons.PATHS.setdefault("checklist", '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/>'
                                    '<path d="M13 12h8"/><path d="M13 18h8"/>')
icons.PATHS.setdefault("pin", '<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1'
                              ' 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1'
                              ' 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>')

UNCHECKED, CHECKED = "☐", "☑"
AUTOSAVE_MS = 600
LIST_WIDTH = 260


def rel_time(ts):
    if not ts:
        return ""
    d = time.time() - ts
    if d < 60:
        return "Just now"
    if d < 3600:
        return f"{int(d // 60)}m ago"
    if d < 86400:
        return f"{int(d // 3600)}h ago"
    if d < 2 * 86400:
        return "Yesterday"
    if d < 7 * 86400:
        return time.strftime("%a", time.localtime(ts))
    return time.strftime("%b %d", time.localtime(ts)).replace(" 0", " ")


def html_to_plain(html):
    if not html:
        return ""
    if "<" not in html:
        return html
    doc = QTextDocument()
    doc.setHtml(html)
    return doc.toPlainText()


def display_title(note, plain):
    if (note.get("title") or "").strip():
        return note["title"].strip()
    for line in plain.splitlines():
        line = line.strip().lstrip(UNCHECKED + CHECKED).strip()
        if line:
            return line[:80]
    return "Untitled note"


# ----------------------------------------------------------------------------- editor
class NoteEdit(QTextEdit):
    """Rich-text editor: plain-text paste, Ctrl+B / Ctrl+I, clickable checkboxes."""

    def __init__(self):
        super().__init__()
        self.setAcceptRichText(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setPlaceholderText("Start typing, or hold Ctrl + Win and talk…")
        self.setFont(theme.ui_font(16))
        self.document().setDefaultFont(theme.ui_font(16))
        self.document().setDocumentMargin(2)
        self.setStyleSheet(f"QTextEdit {{ background: transparent; border: none; padding: 0;"
                           f" font-size: 16px; selection-background-color: {theme.SAND[700]}; }}")

    def insertFromMimeData(self, source):
        if source.hasText():
            self.textCursor().insertText(source.text())
        else:
            super().insertFromMimeData(source)

    def keyPressEvent(self, e):
        if e.matches(QKeySequence.StandardKey.Bold):
            self.toggle_bold()
        elif e.matches(QKeySequence.StandardKey.Italic):
            self.toggle_italic()
        else:
            super().keyPressEvent(e)

    def toggle_bold(self):
        fmt = QTextCharFormat()
        bold = self.fontWeight() < QFont.Weight.DemiBold
        fmt.setFontWeight(QFont.Weight.Bold if bold else QFont.Weight.Normal)
        self.mergeCurrentCharFormat(fmt)

    def toggle_italic(self):
        fmt = QTextCharFormat()
        fmt.setFontItalic(not self.fontItalic())
        self.mergeCurrentCharFormat(fmt)

    def toggle_bullets(self):
        cur = self.textCursor()
        lst = cur.currentList()
        cur.beginEditBlock()
        if lst:
            block, end = self.document().findBlock(cur.selectionStart()), cur.selectionEnd()
            while block.isValid() and block.position() <= end:
                if block.textList():
                    block.textList().remove(block)
                    bf = block.blockFormat()
                    bf.setIndent(0)
                    QTextCursor(block).setBlockFormat(bf)
                block = block.next()
        else:
            cur.createList(QTextListFormat.Style.ListDisc)
        cur.endEditBlock()

    def toggle_checklist(self):
        cur = self.textCursor()
        doc = self.document()
        first, last = doc.findBlock(cur.selectionStart()), doc.findBlock(cur.selectionEnd())
        blocks, b = [], first
        while b.isValid():
            blocks.append(b)
            if b == last:
                break
            b = b.next()
        remove = all(bl.text().startswith((UNCHECKED, CHECKED)) for bl in blocks)
        cur.beginEditBlock()
        for bl in blocks:
            c = QTextCursor(bl)
            if remove:
                n = 2 if bl.text()[1:2] == " " else 1
                c.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, n)
                c.removeSelectedText()
            elif not bl.text().startswith((UNCHECKED, CHECKED)):
                c.insertText(UNCHECKED + " ")
        cur.endEditBlock()

    def mouseReleaseEvent(self, e):
        super().mouseReleaseEvent(e)
        if e.button() != Qt.MouseButton.LeftButton or self.isReadOnly() or self.textCursor().hasSelection():
            return
        c = self.cursorForPosition(e.position().toPoint())
        block = c.block()
        if c.positionInBlock() <= 1 and block.text()[:1] in (UNCHECKED, CHECKED):
            edit = QTextCursor(block)
            edit.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 1)
            edit.insertText(CHECKED if block.text()[0] == UNCHECKED else UNCHECKED)


# ----------------------------------------------------------------------------- list rows
class NoteRow(QFrame):
    clicked = Signal()
    pin_clicked = Signal()
    delete_clicked = Signal()

    def __init__(self, title, preview, when, pinned, selected):
        super().__init__()
        self.setObjectName("NoteRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.selected = selected
        self._paint(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 12, 12)
        lay.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(6)
        if pinned:
            pin = QLabel()
            pin.setPixmap(icons.pixmap("pin", 13, theme.SAND[900]))
            pin.setStyleSheet("background: transparent;")
            top.addWidget(pin)
        tfont = theme.ui_font(15, QFont.Weight.DemiBold if selected else QFont.Weight.Medium)
        t = widgets.label("", 15)
        t.setFont(tfont)
        t.setText(QFontMetrics(tfont).elidedText(title, Qt.TextElideMode.ElideRight, 150 if pinned else 165))
        t.setToolTip(title if len(title) > 20 else "")
        top.addWidget(t, 1)
        self.when = widgets.label(when, 12, color=theme.FOREGROUND_TERTIARY)
        top.addWidget(self.when)
        self.actions = QWidget()
        self.actions.setStyleSheet("background: transparent;")
        al = QHBoxLayout(self.actions)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(0)
        pin_btn = widgets.IconButton("pin", "Unpin" if pinned else "Pin to top", 14, 24)
        pin_btn.clicked.connect(self.pin_clicked.emit)
        del_btn = widgets.IconButton("trash", "Delete note", 14, 24)
        del_btn.clicked.connect(self.delete_clicked.emit)
        al.addWidget(pin_btn)
        al.addWidget(del_btn)
        self.actions.hide()
        top.addWidget(self.actions)
        lay.addLayout(top)
        pfont = theme.ui_font(13)
        p = widgets.label("", 13, color=theme.FOREGROUND_TERTIARY)
        p.setText(QFontMetrics(pfont).elidedText(preview or "No additional text", Qt.TextElideMode.ElideRight, 226))
        lay.addWidget(p)

    def _paint(self, hover):
        bg = theme.SAND[500] if self.selected else (theme.SAND[200] if hover else "transparent")
        self.setStyleSheet(f"#NoteRow {{ background: {bg}; border: none; border-radius: 10px; }}")

    def enterEvent(self, e):
        self._paint(True)
        self.when.hide()
        self.actions.show()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._paint(False)
        self.actions.hide()
        self.when.show()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(e)


# ----------------------------------------------------------------------------- page
class ScratchpadPage(QWidget):
    MAX_WIDTH = 1100

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        # Re-assert the theme below the shell's selector-less "background: transparent" holder.
        self.setStyleSheet(theme.stylesheet())
        self.current_id = None
        self._loading = False
        self._dirty = False
        self._emitting = False
        self._busy = False
        self._plain_cache = {}
        self._scroller = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = widgets.PageHeader("Scratchpad", beta=True)
        self.new_btn = widgets.button("  New note", "Primary", self.new_note)
        self.new_btn.setIcon(icons.icon("plus", 16, theme.PRIMARY_FG, 2.2))
        self.new_btn.setIconSize(QSize(16, 16))
        header.add_right(self.new_btn)
        root.addWidget(header)
        root.addSpacing(26)

        body = QHBoxLayout()
        body.setSpacing(20)
        root.addLayout(body, 1)

        # left column: search + notes list
        left = QVBoxLayout()
        left.setSpacing(12)
        self.search = widgets.SearchField("Search notes")
        self.search.setFixedWidth(LIST_WIDTH)
        self.search.textChanged.connect(lambda _: self.reload_list())
        left.addWidget(self.search)
        self.list_card = QFrame()
        self.list_card.setObjectName("NotesList")
        self.list_card.setFixedWidth(LIST_WIDTH)
        self.list_card.setStyleSheet(f"#NotesList {{ background: {theme.LIST_BG}; border: 1px solid {theme.SECONDARY};"
                                     f" border-radius: 12px; }}")
        cl = QVBoxLayout(self.list_card)
        cl.setContentsMargins(6, 6, 6, 6)
        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.list_holder = QWidget()
        self.list_holder.setObjectName("NotesHolder")
        self.list_holder.setStyleSheet("#NotesHolder { background: transparent; }")
        self.list_lay = QVBoxLayout(self.list_holder)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(2)
        self.list_scroll.setWidget(self.list_holder)
        self.list_scroll.viewport().setStyleSheet("background: transparent;")
        cl.addWidget(self.list_scroll)
        left.addWidget(self.list_card, 1)
        body.addLayout(left)

        # right: editor card
        self.card = QFrame()
        self.card.setObjectName("EditorCard")
        self.card.setStyleSheet(f"#EditorCard {{ background: {theme.CARD}; border: 1px solid {theme.SECONDARY};"
                                f" border-radius: 16px; }}")
        self.card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        ed = QVBoxLayout(self.card)
        ed.setContentsMargins(32, 16, 24, 20)
        ed.setSpacing(0)

        bar = QHBoxLayout()
        bar.setSpacing(2)
        self.editor = NoteEdit()
        for name, tip, slot in (("bold", "Bold (Ctrl+B)", self.editor.toggle_bold),
                                ("italic", "Italic (Ctrl+I)", self.editor.toggle_italic),
                                ("list", "Bulleted list", self.editor.toggle_bullets),
                                ("checklist", "Checklist", self.editor.toggle_checklist)):
            b = widgets.IconButton(name, tip, 17, 32, theme.SAND[950])
            b.clicked.connect(lambda _=False, fn=slot: (fn(), self.editor.setFocus()))
            bar.addWidget(b)
        sep = QFrame()
        sep.setFixedSize(1, 18)
        sep.setStyleSheet(f"background: {theme.SECONDARY};")
        bar.addSpacing(6)
        bar.addWidget(sep)
        bar.addSpacing(6)
        self.transform_btn = widgets.IconButton("transforms", "Transform selection (or the whole note)",
                                                17, 32, theme.SAND[950])
        self.transform_btn.clicked.connect(self._show_transform_menu)
        bar.addWidget(self.transform_btn)
        copy_btn = widgets.IconButton("copy", "Copy note", 17, 32, theme.SAND[950])
        copy_btn.clicked.connect(self.copy_all)
        bar.addWidget(copy_btn)
        bar.addStretch(1)
        self.spinner = Spinner(14, theme.SAND[950])
        bar.addWidget(self.spinner)
        bar.addSpacing(6)
        self.status = widgets.label("", 13, QFont.Weight.Medium, theme.FOREGROUND_TERTIARY)
        bar.addWidget(self.status)
        bar.addSpacing(8)
        ed.addLayout(bar)
        ed.addSpacing(18)

        self.title = QLineEdit()
        self.title.setPlaceholderText("Untitled note")
        self.title.setFont(theme.ui_font(22, QFont.Weight.DemiBold))
        self.title.setStyleSheet("QLineEdit, QLineEdit:focus { background: transparent; border: none; padding: 0;"
                                 " font-size: 22px; font-weight: 600; }")
        self.title.returnPressed.connect(lambda: self.editor.setFocus())
        ed.addWidget(self.title)
        ed.addSpacing(6)
        self.meta = widgets.label("", 13, color=theme.FOREGROUND_TERTIARY)
        ed.addWidget(self.meta)
        ed.addSpacing(16)
        ed.addWidget(self.editor, 1)
        body.addWidget(self.card, 1)

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(AUTOSAVE_MS)
        self.save_timer.timeout.connect(self.save)
        self.title.textEdited.connect(self._edited)
        self.editor.textChanged.connect(self._edited)
        ctx.bus.notes_changed.connect(self._on_notes_changed)

        self.refresh()

    # ------------------------------------------------------------------ sizing
    def showEvent(self, e):
        super().showEvent(e)
        if self._scroller is None:
            w = self.parentWidget()
            while w is not None and not isinstance(w, QScrollArea):
                w = w.parentWidget()
            if w is not None:
                self._scroller = w
                w.viewport().installEventFilter(self)
        self._fit_height()

    def eventFilter(self, obj, ev):
        if self._scroller is not None and obj is self._scroller.viewport() and ev.type() == QEvent.Type.Resize:
            self._fit_height()
        return False

    def _fit_height(self):
        if self._scroller is not None:
            self.setMinimumHeight(max(480, self._scroller.viewport().height() - 44 - 40))

    def hideEvent(self, e):
        self.flush()
        super().hideEvent(e)

    # ------------------------------------------------------------------ data
    def _notes(self):
        return self.ctx.db.query("select id, title, content, created, modified, pinned from notes"
                                 " order by pinned desc, modified desc, id desc")

    def _plain(self, note):
        key = (note["id"], note["modified"])
        if key not in self._plain_cache:
            self._plain_cache[key] = html_to_plain(note["content"] or "")
        return self._plain_cache[key]

    def refresh(self):
        notes = self._notes()
        ids = {n["id"] for n in notes}
        if self.current_id is not None and self.current_id not in ids:
            self.current_id = None
            self._load(None)
        if self.current_id is None and not self._dirty and notes and not self._editor_has_text():
            self._load(notes[0])
        self.reload_list(notes)
        self._update_meta()

    def reload_list(self, notes=None):
        notes = self._notes() if notes is None else notes
        q = self.search.text().strip().lower()
        bar = self.list_scroll.verticalScrollBar()
        pos = bar.value()
        while self.list_lay.count():
            item = self.list_lay.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        shown = 0
        for n in notes:
            plain = self._plain(n)
            title = display_title(n, plain)
            if q and q not in title.lower() and q not in plain.lower():
                continue
            lines = [ln.strip() for ln in plain.splitlines() if ln.strip()]
            if not (n.get("title") or "").strip() and lines:
                lines = lines[1:]
            preview = " ".join(lines)
            row = NoteRow(title, preview, rel_time(n["modified"]), bool(n["pinned"]), n["id"] == self.current_id)
            row.clicked.connect(lambda nid=n["id"]: self.open_note(nid))
            row.pin_clicked.connect(lambda nid=n["id"], p=n["pinned"]: self.set_pinned(nid, not p))
            row.delete_clicked.connect(lambda nid=n["id"], t=title: self.confirm_delete(nid, t))
            self.list_lay.addWidget(row)
            shown += 1
        if not shown:
            msg = "No matching notes" if q else "No notes yet"
            sub = "Try a different search." if q else "Notes you write or dictate here are saved on this PC."
            empty = QWidget()
            empty.setStyleSheet("background: transparent;")
            el = QVBoxLayout(empty)
            el.setContentsMargins(14, 22, 14, 22)
            el.setSpacing(4)
            el.addWidget(widgets.label(msg, 15, QFont.Weight.Medium, theme.SAND[950]))
            el.addWidget(widgets.label(sub, 13, color=theme.FOREGROUND_TERTIARY, wrap=True))
            self.list_lay.addWidget(empty)
        self.list_lay.addStretch(1)
        QTimer.singleShot(0, lambda: bar.setValue(pos))

    def _editor_has_text(self):
        return bool(self.title.text().strip() or self.editor.toPlainText().strip())

    def _load(self, note):
        self._loading = True
        self.save_timer.stop()
        self._dirty = False
        self.current_id = note["id"] if note else None
        self.title.setText((note.get("title") or "") if note else "")
        content = (note.get("content") or "") if note else ""
        if "<" in content:
            self.editor.setHtml(content)
        else:
            self.editor.setPlainText(content)
        self.editor.document().clearUndoRedoStacks()
        self._loading = False
        self._set_status("Saved" if note else "")
        self._update_meta(note)

    # ------------------------------------------------------------------ editing / saving
    def _edited(self, *_):
        if self._loading:
            return
        self._dirty = True
        self._set_status("Editing…")
        self.save_timer.start()

    def flush(self):
        if self._dirty:
            self.save_timer.stop()
            self.save()

    def save(self):
        if not self._dirty:
            return
        self._dirty = False
        title = self.title.text().strip()
        plain = self.editor.toPlainText()
        html = self.editor.toHtml() if plain.strip() else ""
        now = time.time()
        if self.current_id is None:
            if not title and not plain.strip():
                self._set_status("")
                return
            self.current_id = self.ctx.db.insert("notes", title=title, content=html, created=now,
                                                 modified=now, pinned=0)
        else:
            self.ctx.db.update("notes", self.current_id, title=title, content=html, modified=now)
        self._set_status("Saved")
        self._emit_changed()
        self.reload_list()
        self._update_meta()

    def _emit_changed(self):
        self._emitting = True
        try:
            self.ctx.bus.notes_changed.emit()
        finally:
            self._emitting = False

    def _on_notes_changed(self):
        if not self._emitting:
            self.refresh()

    def _leave_current(self):
        """Save the open note; drop it if it was left completely empty."""
        self.flush()
        if self.current_id is not None and not self._editor_has_text():
            self.ctx.db.delete("notes", self.current_id)
            self.current_id = None
            self._emit_changed()

    def new_note(self):
        if self._busy:
            return
        self._leave_current()
        self._load(None)
        self.reload_list()
        self.title.setFocus()

    def open_note(self, note_id):
        if self._busy or note_id == self.current_id:
            return
        self._leave_current()
        rows = self.ctx.db.query("select * from notes where id=?", (note_id,))
        self._load(rows[0] if rows else None)
        self.reload_list()
        self.editor.setFocus()
        self.editor.moveCursor(QTextCursor.MoveOperation.End)

    def set_pinned(self, note_id, pinned):
        self.flush()
        self.ctx.db.update("notes", note_id, pinned=int(pinned))
        self._emit_changed()
        self.reload_list()

    def confirm_delete(self, note_id, title):
        def go():
            if note_id == self.current_id:
                self.save_timer.stop()
                self._dirty = False
            self.ctx.db.delete("notes", note_id)
            self._emit_changed()
            if note_id == self.current_id:
                self.current_id = None
                notes = self._notes()
                self._load(notes[0] if notes else None)
            self.reload_list()
            self.ctx.bus.toast.emit("Note deleted")
        themed(widgets.confirm(self.window(), "Delete this note?", f"“{title}” will be removed from this PC.",
                               "Delete", go, danger=True))

    def copy_all(self):
        text = self.editor.toPlainText()
        title = self.title.text().strip()
        if title:
            text = f"{title}\n\n{text}" if text.strip() else title
        if not text.strip():
            self.ctx.bus.toast.emit("Nothing to copy")
            return
        QGuiApplication.clipboard().setText(text)
        self.ctx.bus.toast.emit("Copied")

    def _set_status(self, text):
        self.status.setText(text)

    def _update_meta(self, note=None):
        if note is None and self.current_id is not None:
            rows = self.ctx.db.query("select modified from notes where id=?", (self.current_id,))
            note = rows[0] if rows else None
        words = len(self.editor.toPlainText().split())
        parts = []
        if note and note.get("modified"):
            parts.append(f"Edited {rel_time(note['modified']).lower()}")
        else:
            parts.append("New note")
        parts.append(f"{words} word{'s' if words != 1 else ''}")
        self.meta.setText("  ·  ".join(parts))

    # ------------------------------------------------------------------ transforms
    def _show_transform_menu(self):
        menu = QMenu(self)
        transforms = engine.list_transforms(self.ctx.db)
        has_sel = self.editor.textCursor().hasSelection()
        head = menu.addAction("Rewrite selection" if has_sel else "Rewrite whole note")
        head.setEnabled(False)
        for t in transforms:
            act = menu.addAction(t["name"])
            act.setToolTip(t["description"] or "")
            act.triggered.connect(lambda _=False, tr=t: self.apply_transform(tr))
        if not transforms:
            menu.addAction("No transforms yet").setEnabled(False)
        menu.addSeparator()
        menu.addAction("Manage transforms…").triggered.connect(lambda: self.ctx.bus.navigate.emit("transforms"))
        menu.exec(self.transform_btn.mapToGlobal(self.transform_btn.rect().bottomLeft()))

    def apply_transform(self, t):
        if self._busy:
            return
        cur = self.editor.textCursor()
        if cur.hasSelection():
            start, end = cur.selectionStart(), cur.selectionEnd()
            text = cur.selection().toPlainText()
        else:
            start, end = 0, max(0, self.editor.document().characterCount() - 1)
            text = self.editor.toPlainText()
        if not text.strip():
            self.ctx.bus.toast.emit("Write something first")
            return
        self._busy = True
        self.editor.setReadOnly(True)
        self.transform_btn.setEnabled(False)
        self.spinner.start()
        self._set_status(f"{t['name']}: working…")
        fmt = formatter_for(self.ctx)
        prompt = t["prompt"]

        def done(result, error):
            self._busy = False
            self.editor.setReadOnly(False)
            self.transform_btn.setEnabled(True)
            self.spinner.stop()
            if error is not None:
                self._set_status("Not applied")
                self.ctx.bus.toast.emit(error_text(error))
                return
            c = QTextCursor(self.editor.document())
            c.setPosition(start)
            c.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            c.insertText(result)        # one undo step: Ctrl+Z restores the original
            self.editor.setTextCursor(c)
            self.ctx.bus.toast.emit(f"{t['name']} applied · Ctrl+Z to undo")
            self.save_timer.stop()
            self.save()

        run_async(self, lambda: engine.run_transform(fmt, prompt, text), done)
