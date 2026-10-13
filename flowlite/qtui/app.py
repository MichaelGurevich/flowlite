"""FlowLite Qt application: Flow Bar + hub window + tray, wired to the dictation engine.

Started by `python -m flowlite` (privacy guard already installed by __main__).
"""

import importlib
import json
import sys
import threading
import time
import urllib.request

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMenu, QSystemTrayIcon, QVBoxLayout, QWidget

from .. import audio, autostart, controller, hotkeys, importer, instance, media, store
from ..dictionary import Dictionary
from ..formatter import OLLAMA_URL, Formatter
from . import flowbar, icons, shell, theme, widgets
from .context import AppContext, Bus

PAGES = [  # key, module, class
    ("home", "home", "HomePage"),
    ("insights", "insights", "InsightsPage"),
    ("dictionary", "dictionary", "DictionaryPage"),
    ("snippets", "dictionary", "SnippetsPage"),
    ("style", "style", "StylePage"),
    ("transforms", "transforms", "TransformsPage"),
    ("scratchpad", "scratchpad", "ScratchpadPage"),
]
ICON_PATH = store.DATA_DIR / "flowlite.ico"


def _placeholder(title, error):
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.addWidget(widgets.PageHeader(title))
    lay.addWidget(widgets.label(f"This page failed to load: {error}", 15, color=theme.FOREGROUND_TERTIARY,
                                wrap=True))
    lay.addStretch(1)
    return w


def load_pages(ctx):
    pages = {}
    for key, module, cls in PAGES:
        try:
            mod = importlib.import_module(f"flowlite.qtui.pages.{module}")
            pages[key] = getattr(mod, cls)(ctx)
        except Exception as e:  # keep the app usable even if one page breaks
            print(f"page {key} failed: {e!r}")
            pages[key] = _placeholder(key.title(), e)
    return pages


def ollama_models():
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as r:
            return sorted(m["name"] for m in json.load(r)["models"])
    except OSError:
        return []


class Signals(QObject):
    history = Signal()


class FlowLiteApp:
    def __init__(self, open_settings=False):
        self.qt = QApplication.instance() or QApplication(sys.argv)
        self.qt.setQuitOnLastWindowClosed(False)
        self.qt.setApplicationName("FlowLite")
        theme.load_fonts()
        self.qt.setStyleSheet(theme.stylesheet())
        if ICON_PATH.exists():
            self.qt.setWindowIcon(QIcon(str(ICON_PATH)))

        s = store.Settings.load()
        db = store.Database()
        store.migrate_legacy(db)
        if s.local_storage == "auto_delete_24h":
            store.History(db).purge_older_than(24 * 3600)
        self.ctx = ctx = AppContext(s, db, store.History(db), Dictionary(db), Bus())
        print(f"FlowLite data: {store.DATA_DIR}")

        # --- engine
        print(f"Loading speech model '{s.whisper_model}'...")
        from ..asr import LocalWhisper
        try:
            self.asr = LocalWhisper(s.whisper_model)
        except Exception as e:
            msg = (f"The speech model '{s.whisper_model}' isn't downloaded yet.\n\nRun once in the FlowLite "
                   f"folder:\n.venv\\Scripts\\python -m flowlite.setup --whisper {s.whisper_model}\n\n({e})")
            print(msg)
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, "FlowLite", 0x40)
            sys.exit(1)
        ctx.formatter = Formatter(s.llm_model)
        keys = s.shortcuts["push_to_talk"].replace("+", " + ").title()
        self.bar = flowbar.FlowBar(keys, show_resting=s.show_resting_bar)
        mic = int(s.mic) if str(s.mic).isdigit() else (s.mic or None)
        ctx.recorder = audio.Recorder(device=mic, warm=s.warm_mic)
        ctx.controller = self.ctl = controller.Controller(
            s, self.asr, ctx.formatter, ctx.dictionary, ctx.history, ctx.recorder, self.bar,
            media.MediaMuter(s.mute_media))
        self.signals = Signals()
        self.signals.history.connect(ctx.bus.history_changed.emit)
        self.ctl.on_history_changed = self.signals.history.emit
        threading.Thread(target=self._connect_formatter, daemon=True).start()

        ctx.extras.update({
            "retry": self.ctl.retry,
            "reload_shortcuts": self.reload_shortcuts,
            "set_autostart": autostart.set_enabled,
            "autostart_enabled": autostart.enabled,
            "ollama_models": ollama_models,
            "import_wispr": self.import_wispr,
            "wispr_available": importer.available,
            "pause_shortcuts": lambda on: setattr(self.listener, "paused", bool(on)),
        })
        ctx.bus.settings_changed.connect(self.apply_settings)

        # --- UI
        self.bar.clicked.connect(self.ctl.start_hands_free)
        self.bar.stop_clicked.connect(self.ctl.start_hands_free)
        self.bar.cancel_clicked.connect(self.ctl.cancel)
        self.bar.menu_builder = self.build_bar_menu
        self.bar.show()
        self.hub = shell.HubWindow(ctx, load_pages(ctx))
        ctx.bus.open_settings.connect(self.open_settings)
        ctx.bus.show_hub.connect(self.show_hub)
        self.tray = self.make_tray()

        self.listener = hotkeys.ChordListener(s.shortcuts, self.ctl.on_hotkey)
        self.listener.start()
        instance.on_show_request(lambda: self.bar.call(self.show_hub))

        self.bar.flash(f"FlowLite is on · hold {keys} to dictate", 4)
        if not s.onboarded:
            QTimer.singleShot(400, self.first_run)
        elif open_settings:
            QTimer.singleShot(300, lambda: self.open_settings("general"))
        print(f"Ready. Hold {keys} and talk.")

    # ----------------------------------------------------------------- engine
    def _connect_formatter(self):
        f = self.ctx.formatter
        if f.warm_up():
            print(f"Formatter: {f.model} via local Ollama")
            return
        print("Ollama isn't running; starting it...")
        if instance.start_ollama():
            for _ in range(30):
                time.sleep(1)
                if f.warm_up():
                    print(f"Formatter: {f.model} via local Ollama")
                    return
        print("Ollama unavailable: basic cleanup only")

    def reload_shortcuts(self):
        self.listener.set_shortcuts(self.ctx.settings.shortcuts)
        self.bar.shortcut_text = self.ctx.settings.shortcuts["push_to_talk"].replace("+", " + ").title()

    def apply_settings(self):
        s = self.ctx.settings
        self.bar.show_resting = s.show_resting_bar
        self.ctl.muter.enabled = s.mute_media
        if self.ctx.formatter.model != s.llm_model:
            self.ctx.formatter.model = s.llm_model
            threading.Thread(target=self.ctx.formatter.warm_up, daemon=True).start()
        mic = int(s.mic) if str(s.mic).isdigit() else (s.mic or None)
        if self.ctx.recorder.device != mic and self.ctl.state == "idle":
            self.ctx.recorder.device = mic

    def import_wispr(self):
        summary = importer.import_all(self.ctx.db, self.ctx.settings)
        self.ctx.bus.history_changed.emit()
        self.ctx.bus.dictionary_changed.emit()
        self.ctx.bus.settings_changed.emit()
        return summary

    # --------------------------------------------------------------------- UI
    def show_hub(self):
        self.hub.show_and_raise()

    def open_settings(self, pane="general"):
        self.show_hub()
        try:
            from .settings import SettingsModal
            SettingsModal(self.ctx, self.hub, pane)
        except Exception as e:
            print(f"settings failed: {e!r}")
            self.ctx.bus.toast.emit("Settings couldn't open")

    def first_run(self):
        s = self.ctx.settings
        s.onboarded = True
        self.ctx.save_settings()
        self.show_hub()
        if not importer.available():
            return
        m = widgets.Modal(self.hub, 520)
        m.body.addWidget(widgets.display_label("Welcome to FlowLite", 34))
        m.body.addWidget(widgets.label(
            "FlowLite found Wispr Flow's data on this computer. Bring over your dictation history, "
            "dictionary, snippets and style choices? It's copied locally — nothing is uploaded.",
            15, color=theme.SAND[950], wrap=True))
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(widgets.button("Not now", "Secondary", m.close_modal))

        def do_import():
            m.close_modal()
            summary = self.import_wispr()
            self.ctx.bus.toast.emit(f"Imported {summary['history']} dictations, {summary['words']} words, "
                                    f"{summary['snippets']} snippets")
        row.addWidget(widgets.button("Import my Wispr data", "Primary", do_import))
        m.body.addLayout(row)
        m.open()

    def _mic_menu(self, menu):
        import sounddevice as sd
        sub = menu.addMenu("Microphone")
        current = str(self.ctx.settings.mic or "")
        default = sub.addAction("Default microphone")
        default.setCheckable(True)
        default.setChecked(current == "")
        default.triggered.connect(lambda: self._set_mic(""))
        try:
            hostapi = sd.default.hostapi
            for idx, dev in enumerate(sd.query_devices()):
                if dev["max_input_channels"] > 0 and dev["hostapi"] == hostapi:
                    a = sub.addAction(dev["name"])
                    a.setCheckable(True)
                    a.setChecked(current == str(idx))
                    a.triggered.connect(lambda _=False, i=idx: self._set_mic(str(i)))
        except Exception:
            pass

    def _set_mic(self, value):
        self.ctx.settings.mic = value
        self.ctx.save_settings()

    def build_bar_menu(self, menu):
        menu.addAction("Hide for 1 hour", lambda: self.bar.hide_for(3600))
        menu.addAction("Open FlowLite", self.show_hub)
        menu.addAction("Settings", lambda: self.open_settings("general"))
        menu.addSeparator()
        self._mic_menu(menu)
        menu.addSeparator()
        menu.addAction("Transcript history", lambda: (self.show_hub(), self.ctx.bus.navigate.emit("home")))
        menu.addAction("Paste last transcript", lambda: threading.Thread(
            target=self.ctl._run_action, args=("paste_last",), daemon=True).start())

    def make_tray(self):
        tray = QSystemTrayIcon(QIcon(str(ICON_PATH)) if ICON_PATH.exists() else QIcon(icons.pixmap("logo", 32)))
        tray.setToolTip("FlowLite — local dictation")
        menu = QMenu()

        def rebuild():
            menu.clear()
            menu.addAction("Open FlowLite", self.show_hub)
            menu.addSeparator()
            keys = self.ctx.settings.shortcuts.get("paste_last", "").replace("+", " + ").title()
            menu.addAction(f"Paste last transcript    {keys}", lambda: threading.Thread(
                target=self.ctl._run_action, args=("paste_last",), daemon=True).start())
            last = self.ctx.history.last_text() or ""
            preview = menu.addAction((last[:48] + "…") if len(last) > 48 else (last or "No dictations yet"))
            preview.setEnabled(False)
            menu.addSeparator()
            menu.addAction("Shortcuts…", lambda: self.open_settings("shortcuts"))
            self._mic_menu(menu)
            menu.addAction("Languages…", lambda: self.open_settings("general"))
            menu.addSeparator()
            menu.addAction("Quit FlowLite", self.quit)
        menu.aboutToShow.connect(rebuild)
        rebuild()
        tray.setContextMenu(menu)
        tray.activated.connect(lambda reason: self.show_hub()
                               if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
        tray.show()
        return tray

    def quit(self):
        self.listener.stop()
        self.ctx.recorder.close()
        self.tray.hide()
        self.qt.quit()

    def _debug_snapshot(self, path):
        """FLOWLITE_SNAPSHOT=<file.png>: save the hub window and quit (used by smoke tests).
        FLOWLITE_SNAPSHOT_PAGE=<page key> / FLOWLITE_SNAPSHOT_SETTINGS=<pane> pick what to show."""
        import os
        self.show_hub()
        if os.environ.get("FLOWLITE_SNAPSHOT_PAGE"):
            self.ctx.bus.navigate.emit(os.environ["FLOWLITE_SNAPSHOT_PAGE"])
        if os.environ.get("FLOWLITE_SNAPSHOT_SETTINGS"):
            self.open_settings(os.environ["FLOWLITE_SNAPSHOT_SETTINGS"])
        QTimer.singleShot(2500, lambda: (self.hub.grab().save(path), print(f"snapshot saved {path}"),
                                         self.quit()))

    def run(self):
        import os
        if os.environ.get("FLOWLITE_SNAPSHOT"):
            QTimer.singleShot(3000, lambda: self._debug_snapshot(os.environ["FLOWLITE_SNAPSHOT"]))
        timer = QTimer()
        timer.start(250)  # lets Ctrl+C reach Python while Qt's loop runs
        timer.timeout.connect(lambda: None)
        try:
            return self.qt.exec()
        except KeyboardInterrupt:
            self.quit()
