"""Offline end-to-end check with the privacy guard on (no mic, hotkey or paste needed):

Windows TTS -> 40 ms blocks fed in real time -> streaming Whisper -> local Ollama
formatter -> Wispr-style post-processing.

    .venv\\Scripts\\python selftest.py
"""

import os
import subprocess
import sys
import tempfile
import time
import urllib.request
import wave

import numpy as np

from flowlite import privacy

privacy.install()

from flowlite import categories, context, postprocess, store  # noqa: E402
from flowlite.asr import LocalWhisper, StreamingSession  # noqa: E402
from flowlite.formatter import Formatter  # noqa: E402

PHRASE = ("so I was thinking we should ship the local version on friday. no wait, on thursday. "
          "and can you also send me the report by tomorrow morning")

TTS = r"""Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToWaveFile($env:FLOWLITE_WAV, $f); $s.Speak($env:FLOWLITE_TEXT); $s.Dispose()"""


def main():
    try:
        urllib.request.urlopen("https://example.com", timeout=3)
        print("FAIL: privacy guard let an outbound request through")
        return 1
    except OSError:
        print("privacy guard: outbound blocked ✓")

    wav = os.path.join(tempfile.mkdtemp(), "phrase.wav")
    subprocess.run(["powershell", "-NoProfile", "-Command", TTS], check=True,
                   env={**os.environ, "FLOWLITE_WAV": wav, "FLOWLITE_TEXT": PHRASE})
    with wave.open(wav) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)

    s = store.Settings()
    asr = LocalWhisper(s.whisper_model)
    fmt = Formatter(s.llm_model)
    print(f"ollama: {'ready' if fmt.warm_up() else 'NOT RUNNING (rule-based only)'}")

    session = StreamingSession(asr, None, ["FlowLite"])
    for i in range(0, len(pcm), 640):  # real-time feed, like the microphone
        session.feed(pcm[i:i + 640])
        time.sleep(0.04)
    t = time.perf_counter()
    raw, _ = session.finish()
    tail_ms = int((time.perf_counter() - t) * 1000)

    ctx = context.DictationContext(app="slack.exe", before_text="")
    app_type, cat = categories.classify(ctx.app)
    style = s.styles[cat]
    text, llm_ms, used = fmt.format(raw, app_type, style, s.cleanup_level)
    text, _ = postprocess.run(text, s, app_type, style, ctx, raw)

    print(f"audio    : {len(pcm) / 16000:.1f} s")
    print(f"asr      : {raw!r}")
    print(f"final    : {text!r}  ({app_type}/{style}, llm used={used})")
    print(f"latency  : tail ASR {tail_ms} ms + LLM {llm_ms} ms after release")
    ok = "thursday" in text.lower() and "report" in text.lower()
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
