"""Create a "FlowLite" icon on the Desktop and in the Start menu.

The shortcut runs FlowLite with pythonw.exe: no console window, just the floating
Flow bar and a tray icon, like Wispr Flow. Opening it again while FlowLite is running
brings up the FlowLite window instead of starting a second copy.

    python -m flowlite.shortcut          # create / update the shortcuts
    python -m flowlite.shortcut remove
"""

import os
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

from .store import DATA_DIR

PROJECT = Path(__file__).resolve().parent.parent
ICON = DATA_DIR / "flowlite.ico"


def make_icon(path=ICON):
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((8, 8, size - 8, size - 8), radius=56, fill=(16, 16, 20, 255))
    d.rounded_rectangle((36, 88, size - 36, size - 88), radius=40,
                        fill=(30, 30, 36, 255), outline=(110, 110, 124, 255), width=6)
    heights = (20, 36, 50, 36, 20)
    for i, h in enumerate(heights):
        x = size / 2 + (i - 2) * 30
        d.line((x, size / 2 - h / 2, x, size / 2 + h / 2), fill=(244, 244, 246, 255), width=14)
        d.ellipse((x - 7, size / 2 - h / 2 - 7, x + 7, size / 2 - h / 2 + 7), fill=(244, 244, 246, 255))
        d.ellipse((x - 7, size / 2 + h / 2 - 7, x + 7, size / 2 + h / 2 + 7), fill=(244, 244, 246, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    return path


def _special_folder(name):
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          f"[Environment]::GetFolderPath('{name}')"],
                         capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


def _write_lnk(lnk, target, arguments, workdir, icon, description):
    script = (
        "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:FL_LNK);"
        "$s.TargetPath = $env:FL_TARGET; $s.Arguments = $env:FL_ARGS;"
        "$s.WorkingDirectory = $env:FL_DIR; $s.IconLocation = $env:FL_ICON;"
        "$s.Description = $env:FL_DESC; $s.Save()"
    )
    env = {**os.environ, "FL_LNK": str(lnk), "FL_TARGET": str(target), "FL_ARGS": arguments,
           "FL_DIR": str(workdir), "FL_ICON": f"{icon},0", "FL_DESC": description}
    subprocess.run(["powershell", "-NoProfile", "-Command", script], env=env, check=True)


def shortcut_paths():
    return [_special_folder("Desktop") / "FlowLite.lnk", _special_folder("Programs") / "FlowLite.lnk"]


def create():
    icon = make_icon()
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    for lnk in shortcut_paths():
        _write_lnk(lnk, pythonw, "-m flowlite", PROJECT, icon,
                   "FlowLite: private, local voice dictation (hold Ctrl+Win to talk)")
        print(f"Created {lnk}")


def remove():
    for lnk in shortcut_paths():
        lnk.unlink(missing_ok=True)
        print(f"Removed {lnk}")


if __name__ == "__main__":
    remove() if sys.argv[1:] == ["remove"] else create()
