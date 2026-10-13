"""App + textbox context (Wispr helper: UI Automation TextPattern / ValuePattern).

Captured at dictation start while the target app still has focus: app, window title,
text before/after the caret (whole field and current line) and the selection.
"""

from dataclasses import dataclass

from . import win32

LLM_CONTEXT_CHARS = 500
FIELD_LIMIT = 20000


@dataclass
class DictationContext:
    app: str = ""
    window_title: str = ""
    before_text: str = ""     # field text before the caret
    after_text: str = ""      # field text after the caret
    selected_text: str = ""
    element_key: tuple = None  # identifies the focused field for edit observation

    @property
    def line_before(self):
        return self.before_text.rsplit("\n", 1)[-1]

    @property
    def line_after(self):
        return self.after_text.split("\n", 1)[0]


def capture(read_textbox=True):
    app, title = win32.foreground_app()
    ctx = DictationContext(app=app, window_title=title)
    if read_textbox:
        _fill_from_uia(ctx)
    return ctx


def _import_uia():
    try:
        import uiautomation as auto
        return auto
    except ImportError:
        return None


def _element_key(ctrl):
    try:
        return (ctrl.ProcessId, ctrl.NativeWindowHandle, ctrl.ControlTypeName, ctrl.AutomationId,
                ctrl.ClassName)
    except Exception:
        return None


def _fill_from_uia(ctx):
    auto = _import_uia()
    if auto is None:
        return
    try:
        with auto.UIAutomationInitializerInThread():
            ctrl = auto.GetFocusedControl()
            if ctrl is None:
                return
            ctx.element_key = _element_key(ctrl)
            pattern = ctrl.GetPattern(auto.PatternId.TextPattern)
            if pattern is not None:
                selection = pattern.GetSelection()
                if selection:
                    sel = selection[0]
                    ctx.selected_text = sel.GetText(FIELD_LIMIT)
                    before = pattern.DocumentRange.Clone()
                    before.MoveEndpointByRange(auto.TextPatternRangeEndpoint.End, sel,
                                               auto.TextPatternRangeEndpoint.Start)
                    after = pattern.DocumentRange.Clone()
                    after.MoveEndpointByRange(auto.TextPatternRangeEndpoint.Start, sel,
                                              auto.TextPatternRangeEndpoint.End)
                    ctx.before_text = before.GetText(FIELD_LIMIT)
                    ctx.after_text = after.GetText(FIELD_LIMIT)
                    return
            value = ctrl.GetPattern(auto.PatternId.ValuePattern)
            if value is not None and not value.IsReadOnly:
                # No caret position available: assume the caret is at the end.
                ctx.before_text = value.Value or ""
    except Exception:
        pass


def read_focused_field():
    """Return (element_key, full_text) of the focused field, or (None, None)."""
    auto = _import_uia()
    if auto is None:
        return None, None
    try:
        with auto.UIAutomationInitializerInThread():
            ctrl = auto.GetFocusedControl()
            if ctrl is None:
                return None, None
            key = _element_key(ctrl)
            pattern = ctrl.GetPattern(auto.PatternId.TextPattern)
            if pattern is not None:
                return key, pattern.DocumentRange.GetText(FIELD_LIMIT)
            value = ctrl.GetPattern(auto.PatternId.ValuePattern)
            if value is not None:
                return key, value.Value
    except Exception:
        pass
    return None, None
