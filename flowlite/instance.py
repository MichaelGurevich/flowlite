"""Single instance + "show window" signal, and background-mode helpers."""

import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.restype = ctypes.c_void_p
kernel32.CreateMutexW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p)
kernel32.CreateEventW.restype = ctypes.c_void_p
kernel32.CreateEventW.argtypes = (ctypes.c_void_p, ctypes.c_bool, ctypes.c_bool, ctypes.c_wchar_p)
kernel32.OpenEventW.restype = ctypes.c_void_p
kernel32.OpenEventW.argtypes = (ctypes.c_uint32, ctypes.c_bool, ctypes.c_wchar_p)
kernel32.SetEvent.argtypes = (ctypes.c_void_p,)
kernel32.WaitForSingleObject.argtypes = (ctypes.c_void_p, ctypes.c_uint32)

ERROR_ALREADY_EXISTS = 183
EVENT_MODIFY_STATE = 0x0002
MUTEX_NAME = "Local\\FlowLite.Instance"
SHOW_EVENT = "Local\\FlowLite.Show"
_mutex = None


def claim_or_signal():
    """Return True if this is the only FlowLite. Otherwise ask the running one to show
    its window and return False."""
    global _mutex
    _mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.get_last_error() != ERROR_ALREADY_EXISTS:
        return True
    event = kernel32.OpenEventW(EVENT_MODIFY_STATE, False, SHOW_EVENT)
    if event:
        kernel32.SetEvent(event)
    return False


def on_show_request(callback):
    """Call callback() whenever another launch asks this instance to show itself."""
    event = kernel32.CreateEventW(None, False, False, SHOW_EVENT)

    def wait():
        while True:
            if kernel32.WaitForSingleObject(event, 0xFFFFFFFF) == 0:
                callback()
    threading.Thread(target=wait, daemon=True).start()


def redirect_output_if_headless(log_path):
    """pythonw.exe has no console: send prints and errors to a log file instead."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    log = open(log_path, "a", encoding="utf-8", buffering=1)
    log.write(f"\n==== FlowLite started {time.strftime('%Y-%m-%d %H:%M:%S')} ====\n")
    sys.stdout = sys.stderr = log


def start_ollama():
    """Launch Ollama's tray app (or `ollama serve`) hidden, if it's installed."""
    candidates = [Path(os.environ.get("LOCALAPPDATA", "")) / "Programs/Ollama/ollama app.exe"]
    exe = shutil.which("ollama")
    if exe:
        candidates.append(Path(exe).with_name("ollama app.exe"))
    for app in candidates:
        if app.exists():
            subprocess.Popen([str(app)], creationflags=subprocess.DETACHED_PROCESS)
            return True
    if exe:
        subprocess.Popen([exe, "serve"], creationflags=subprocess.CREATE_NO_WINDOW)
        return True
    return False
