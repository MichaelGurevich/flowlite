"""Start/stop cues. Synthesized here (original sounds, not Wispr's assets)."""

import numpy as np
import sounddevice as sd

RATE = 44100


def _tone(freqs, ms=70, gap_ms=15, volume=0.18):
    parts = []
    for f in freqs:
        t = np.arange(int(RATE * ms / 1000)) / RATE
        env = np.minimum(1.0, t / 0.008) * np.exp(-t * 28)
        parts.append(np.sin(2 * np.pi * f * t) * env)
        parts.append(np.zeros(int(RATE * gap_ms / 1000)))
    return (np.concatenate(parts) * volume).astype(np.float32)


START = _tone([660, 990])
STOP = _tone([990, 660])
CANCEL = _tone([440, 330], ms=60)
LOCK = _tone([660, 880, 1100], ms=55)
ERROR = _tone([300, 300], ms=90)


def play(sound, enabled=True):
    if not enabled:
        return
    try:
        sd.play(sound, RATE, blocking=False)
    except sd.PortAudioError:
        pass
