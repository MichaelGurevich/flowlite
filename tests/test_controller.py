"""Drive the real Controller with simulated hotkey events (no mic, no keyboard, no paste).

    .venv\\Scripts\\python -m pytest -q tests
"""

import threading
import time

import numpy as np
import pytest

from flowlite import controller as ctl_mod
from flowlite import context, store
from flowlite.dictionary import Dictionary


class FakeRecorder:
    def __init__(self):
        self.on_level = None
        self.sink = None
        self.starts = self.stops = 0

    def start(self, sink):
        self.starts += 1
        self.sink = sink
        tone = (np.sin(np.arange(640) / 3) * 8000).astype(np.int16)
        for _ in range(30):  # 1.2 s of "speech"
            sink(tone)

    def stop(self):
        self.stops += 1
        self.sink = None


class FakeASR:
    def transcribe(self, audio, language=None, prompt=None):
        return "um send the report to kathy by friday", "en"


class FakeFormatter:
    def format(self, raw, app_type, style, level, before, vocab):
        return "Send the report to Kathy by Friday.", 5, True

    def command(self, instruction, selected):
        return f"[{instruction}] {selected}", 5


class FakeOverlay:
    def __init__(self):
        self.states, self.flashes = [], []

    def set_state(self, s):
        self.states.append(s)

    def set_level(self, v):
        pass

    def flash(self, text, seconds=2.5, subtitle=""):
        self.flashes.append(text)


class FakeMuter:
    def mute(self):
        pass

    def unmute(self):
        pass


@pytest.fixture
def env(monkeypatch, tmp_path):
    inserted = []
    monkeypatch.setattr(ctl_mod.insert, "insert_text", lambda text, mode="paste": inserted.append(text))
    monkeypatch.setattr(ctl_mod.insert, "selected_text_via_copy", lambda: "hello world")
    monkeypatch.setattr(ctl_mod.win32, "send_mask_key", lambda: None)
    monkeypatch.setattr(ctl_mod.sounds, "play", lambda *a, **k: None)
    monkeypatch.setattr(ctl_mod.context, "capture",
                        lambda read_textbox=True: context.DictationContext(app="slack.exe"))
    s = store.Settings()
    s.learn_from_edits = False
    db = store.Database(tmp_path / "t.sqlite")
    c = ctl_mod.Controller(s, FakeASR(), FakeFormatter(), Dictionary(db), store.History(db),
                           FakeRecorder(), FakeOverlay(), FakeMuter())
    return c, inserted


def wait_idle(c, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        if c.state == "idle":
            return
        time.sleep(0.02)
    raise AssertionError(f"still {c.state}")


def test_hold_to_talk_inserts_text(env):
    c, inserted = env
    c.on_hotkey("down", "push_to_talk")
    assert c.state == "listening" and c.mode == "ptt"
    time.sleep(0.6)
    c.on_hotkey("up", "push_to_talk")
    assert c.state == "processing"
    wait_idle(c)
    # slack = work messaging -> formal style keeps the period; empty line after -> trailing space
    assert inserted == ["Send the report to Kathy by Friday. "]
    assert c.history.last_text() == "Send the report to Kathy by Friday."


def test_short_tap_is_dismissed_with_hint(env):
    c, inserted = env
    c.on_hotkey("down", "push_to_talk")
    c.on_hotkey("up", "push_to_talk")
    time.sleep(0.7)
    assert c.state == "idle" and inserted == []
    assert any("Hold" in f for f in c.overlay.flashes)


def test_double_tap_locks_hands_free_then_press_stops(env):
    c, inserted = env
    c.on_hotkey("down", "push_to_talk")
    c.on_hotkey("up", "push_to_talk")
    c.on_hotkey("down", "push_to_talk")
    assert c.locked and c.mode == "popo"
    c.on_hotkey("up", "push_to_talk")
    time.sleep(0.7)
    assert c.state == "listening"  # releasing doesn't stop a locked dictation
    c.on_hotkey("down", "push_to_talk")
    wait_idle(c)
    assert len(inserted) == 1


def test_hands_free_shortcut_and_escape(env):
    c, inserted = env
    c.on_hotkey("down", "hands_free")
    assert c.locked
    time.sleep(0.1)
    c.on_hotkey("down", "dismiss")
    assert c.state == "idle" and inserted == []


def test_ptt_plus_alt_upgrades_to_command_mode(env):
    c, inserted = env
    c.on_hotkey("down", "push_to_talk")
    c.on_hotkey("down", "command_mode")
    assert c.mode == "command"
    time.sleep(0.6)
    c.on_hotkey("up", "command_mode")
    wait_idle(c)
    assert inserted == ["[um send the report to kathy by friday] hello world"]


def test_busy_press_is_ignored(env):
    c, _ = env
    c.state = "processing"
    c.on_hotkey("down", "push_to_talk")
    assert c.state == "processing"
    assert any("Still transcribing" in f for f in c.overlay.flashes)
