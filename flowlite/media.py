"""Mute other apps' audio while dictating (Wispr on Windows: MuteAllAppSessions).

Mutes every WASAPI audio session except FlowLite's own, then restores exactly the
sessions it muted. Runs on its own thread because COM calls can take a few ms.
"""

import os
import threading


class MediaMuter:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self._muted = []
        self._lock = threading.Lock()

    def mute(self):
        if self.enabled:
            threading.Thread(target=self._mute, daemon=True).start()

    def unmute(self):
        if self.enabled:
            threading.Thread(target=self._unmute, daemon=True).start()

    def _sessions(self):
        from pycaw.pycaw import AudioUtilities
        return AudioUtilities.GetAllSessions()

    def _mute(self):
        try:
            import comtypes
            comtypes.CoInitialize()
            with self._lock:
                for s in self._sessions():
                    if s.ProcessId in (0, os.getpid()) or s.SimpleAudioVolume is None:
                        continue
                    if not s.SimpleAudioVolume.GetMute():
                        s.SimpleAudioVolume.SetMute(1, None)
                        self._muted.append(s.ProcessId)
        except Exception as e:
            print(f"  [media] mute failed: {e}")

    def _unmute(self):
        try:
            import comtypes
            comtypes.CoInitialize()
            with self._lock:
                pids, self._muted = set(self._muted), []
                for s in self._sessions():
                    if s.ProcessId in pids and s.SimpleAudioVolume is not None:
                        s.SimpleAudioVolume.SetMute(0, None)
        except Exception as e:
            print(f"  [media] unmute failed: {e}")
