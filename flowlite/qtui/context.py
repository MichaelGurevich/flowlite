"""Shared app context + event bus handed to every page."""

from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal


class Bus(QObject):
    history_changed = Signal()
    dictionary_changed = Signal()
    notes_changed = Signal()
    settings_changed = Signal()
    toast = Signal(str)                 # small black pill at the bottom of the hub
    navigate = Signal(str)              # page key: home, insights, dictionary, snippets, style, transforms, scratchpad
    open_settings = Signal(str)         # settings pane key: general, system, experimental, models, privacy
    show_hub = Signal()


@dataclass
class AppContext:
    settings: object                    # store.Settings
    db: object                          # store.Database
    history: object                     # store.History
    dictionary: object                  # dictionary.Dictionary
    bus: Bus
    formatter: object = None            # formatter.Formatter (local Ollama)
    controller: object = None           # controller.Controller (dictation state machine)
    recorder: object = None             # audio.Recorder
    extras: dict = field(default_factory=dict)

    def save_settings(self):
        self.settings.save()
        self.bus.settings_changed.emit()
