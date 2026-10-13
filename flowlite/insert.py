"""Insert text into the focused app, the way Wispr Flow's Windows helper does.

Wispr: save clipboard -> put dictation on clipboard -> SendInput Ctrl+V ->
restore the old clipboard unless something else changed it meanwhile.
"""

import time

from . import win32


def paste_text(text, restore_delay=0.35):
    previous = None
    try:
        previous = win32.get_clipboard_text()
    except OSError:
        pass

    win32.release_stuck_modifiers()
    our_seq = win32.set_clipboard_text(text, exclude_from_history=True)
    win32.send_ctrl_v()

    # The target app reads the clipboard asynchronously after it processes Ctrl+V.
    # Wispr detects that read via delayed rendering; a short wait is the simple version.
    time.sleep(restore_delay)
    if previous is None:
        return
    if win32.clipboard_sequence() != our_seq:
        return  # clipboard changed since our paste: don't clobber the user's new copy
    win32.set_clipboard_text(previous)


def type_text(text):
    win32.release_stuck_modifiers()
    win32.type_unicode(text)


def insert_text(text, mode="paste"):
    if not text:
        return
    if mode == "type":
        type_text(text)
    else:
        paste_text(text)


def selected_text_via_copy(timeout=0.4):
    """Read the current selection by simulating Ctrl+C, then restore the clipboard.

    Same technique as Wispr's GetSelectedTextViaCopy helper request.
    Returns "" when nothing is selected (the clipboard sequence doesn't change).
    """
    previous = None
    try:
        previous = win32.get_clipboard_text()
    except OSError:
        pass
    before = win32.clipboard_sequence()
    win32.release_stuck_modifiers()
    win32.send_ctrl_c()
    deadline = time.monotonic() + timeout
    while win32.clipboard_sequence() == before and time.monotonic() < deadline:
        time.sleep(0.01)
    if win32.clipboard_sequence() == before:
        return ""
    time.sleep(0.03)
    try:
        selected = win32.get_clipboard_text() or ""
    except OSError:
        selected = ""
    if previous is not None:
        win32.set_clipboard_text(previous)
    return selected
