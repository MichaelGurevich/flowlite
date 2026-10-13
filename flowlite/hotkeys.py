"""Global chord detection over a low-level keyboard hook (pynput / WH_KEYBOARD_LL).

Wispr's helper forwards raw key events and a JS state machine matches chords stored
as sorted virtual-key codes ("162+91" = Ctrl+Win). Here shortcuts are written as
"ctrl+win", "ctrl+win+space", "shift+alt+z"; left/right modifiers are treated alike.
Injected events (FlowLite's own Ctrl+V / Ctrl+C) are ignored.
"""

from pynput import keyboard

VK_NAMES = {
    0x10: "shift", 0xA0: "shift", 0xA1: "shift",
    0x11: "ctrl", 0xA2: "ctrl", 0xA3: "ctrl",
    0x12: "alt", 0xA4: "alt", 0xA5: "alt",
    0x5B: "win", 0x5C: "win",
    0x20: "space", 0x1B: "esc", 0x0D: "enter", 0x09: "tab", 0x08: "backspace",
}
VK_NAMES.update({vk: f"f{vk - 0x6F}" for vk in range(0x70, 0x88)})
VK_NAMES.update({vk: chr(vk).lower() for vk in range(0x41, 0x5B)})
VK_NAMES.update({vk: chr(vk) for vk in range(0x30, 0x3A)})
MODIFIERS = {"shift", "ctrl", "alt", "win"}


def parse(shortcut):
    keys = frozenset(k.strip().lower() for k in shortcut.split("+") if k.strip())
    return frozenset("win" if k in ("cmd", "meta", "super") else k for k in keys)


def key_name(key):
    vk = getattr(key, "vk", None)
    if vk is None and hasattr(key, "value"):
        vk = getattr(key.value, "vk", None)
    if vk is None:
        return None
    return VK_NAMES.get(vk, f"vk{vk}")


class ChordListener:
    """Calls on_event(kind, name) with kind in {"down", "up", "all_up"}.

    "down": the pressed-key set just became exactly a shortcut's key set.
    "up":   a key of a held shortcut was released.
    "all_up": every key is released (Wispr fires paste-last only then).
    """

    def __init__(self, shortcuts, on_event):
        self.shortcuts = {name: parse(s) for name, s in shortcuts.items() if s}
        self.on_event = on_event
        self.pressed = set()
        self.held = set()
        self.paused = False   # Settings → Shortcuts records keys without triggering actions
        self._listener = None

    def _on_press(self, key, injected=False):
        if injected or self.paused:
            return
        name = key_name(key)
        if name is None or name in self.pressed:
            return  # key auto-repeat
        self.pressed.add(name)
        for sc_name, keys in self.shortcuts.items():
            if keys == self.pressed:
                self.held.add(sc_name)
                self.on_event("down", sc_name)

    def _on_release(self, key, injected=False):
        if injected:
            return
        if self.paused:
            self.pressed.clear()
            self.held.clear()
            return
        name = key_name(key)
        if name is None:
            return
        for sc_name in list(self.held):
            if name in self.shortcuts[sc_name]:
                self.held.discard(sc_name)
                self.on_event("up", sc_name)
        self.pressed.discard(name)
        if not self.pressed:
            self.on_event("all_up", None)

    def set_shortcuts(self, shortcuts):
        """Swap the shortcut table at runtime (Settings → Shortcuts)."""
        self.shortcuts = {name: parse(s) for name, s in shortcuts.items() if s}
        self.held.clear()

    def start(self):
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()

    def stop(self):
        if self._listener:
            self._listener.stop()
