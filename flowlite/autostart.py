"""Start FlowLite when you sign in to Windows (like Wispr Flow), without a console window.

    python -m flowlite.autostart on
    python -m flowlite.autostart off
"""

import os
import sys
from pathlib import Path

STARTUP = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs/Startup"
LAUNCHER = STARTUP / "FlowLite.cmd"


def enabled():
    return LAUNCHER.exists()


def enable():
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    project = Path(__file__).resolve().parent.parent
    LAUNCHER.write_text(f'@echo off\r\ncd /d "{project}"\r\nstart "" "{pythonw}" -m flowlite\r\n',
                        encoding="utf-8")


def disable():
    LAUNCHER.unlink(missing_ok=True)


def set_enabled(on):
    enable() if on else disable()


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "on"
    set_enabled(action != "off")
    print(f"Autostart {'enabled' if enabled() else 'disabled'}.")


if __name__ == "__main__":
    main()
