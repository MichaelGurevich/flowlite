"""FlowLite: local, private Wispr Flow-style dictation for Windows."""

import sys

# Windows consoles default to a legacy code page; never crash on printing "→" or "…".
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
