"""Microphone capture: 16 kHz mono int16, 40 ms blocks (same shape as Wispr's AudioWorklet).

Like Wispr, echo cancellation / noise suppression / AGC are not applied: Whisper does
better on the raw signal. With warm=True the stream stays open between dictations and
a 300 ms pre-roll is kept, so the first syllable is never clipped (the Windows mic
indicator then stays on while FlowLite runs).
"""

import collections
import threading

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 16000
BLOCK = 640  # 40 ms
PREROLL_BLOCKS = 8


class Recorder:
    def __init__(self, device=None, warm=False):
        self.device = device
        self.warm = warm
        self._stream = None
        self._sink = None
        self._lock = threading.Lock()
        self._preroll = collections.deque(maxlen=PREROLL_BLOCKS)
        self._rate = SAMPLE_RATE
        self._resample_buf = np.zeros(0, dtype=np.float32)
        self.on_level = None  # callback(dBFS) for the overlay waveform
        if warm:
            self._open()

    def _open(self):
        if self._stream is not None:
            return
        try:
            self._rate = SAMPLE_RATE
            self._stream = self._make_stream(SAMPLE_RATE, BLOCK)
        except sd.PortAudioError:
            # Some host APIs refuse 16 kHz; capture at the device rate and resample.
            info = sd.query_devices(self.device, "input")
            self._rate = int(info["default_samplerate"])
            self._stream = self._make_stream(self._rate, int(self._rate * 0.04))
        self._stream.start()

    def _make_stream(self, rate, blocksize):
        return sd.InputStream(samplerate=rate, channels=1, dtype="int16", blocksize=blocksize,
                              device=self.device, callback=self._callback)

    def _callback(self, indata, frames, time_info, status):
        block = indata[:, 0].copy()
        if self._rate != SAMPLE_RATE:
            block = self._to_16k(block)
            if block is None:
                return
        with self._lock:
            sink = self._sink
            if sink is None:
                self._preroll.append(block)
                return
        sink(block)
        if self.on_level:
            f = block.astype(np.float32) / 32768.0
            self.on_level(20 * np.log10(max(float(np.sqrt(np.mean(f * f))), 1e-10)))

    def _to_16k(self, block):
        f = block.astype(np.float32)
        n = int(round(len(f) * SAMPLE_RATE / self._rate))
        res = np.interp(np.linspace(0, len(f), n, endpoint=False), np.arange(len(f)), f)
        self._resample_buf = np.concatenate([self._resample_buf, res.astype(np.float32)])
        if len(self._resample_buf) < BLOCK:
            return None
        out, self._resample_buf = self._resample_buf[:BLOCK], self._resample_buf[BLOCK:]
        return out.astype(np.int16)

    def start(self, sink):
        """Begin delivering 40 ms int16 blocks to sink(block)."""
        self._open()
        with self._lock:
            preroll = list(self._preroll) if self.warm else []
            self._preroll.clear()
            self._sink = sink
        for block in preroll:
            sink(block)

    def stop(self):
        with self._lock:
            self._sink = None
        if not self.warm and self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    def close(self):
        self.warm = False
        self.stop()


def resample(audio, src_rate, dst_rate=SAMPLE_RATE):
    """Linear resampling of float32 audio (used for files and non-16 kHz devices)."""
    n = int(round(len(audio) * dst_rate / src_rate))
    x_old = np.linspace(0.0, 1.0, num=len(audio), endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=n, endpoint=False)
    return np.interp(x_new, x_old, audio).astype(np.float32)
