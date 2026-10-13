"""Local speech-to-text with faster-whisper, plus progressive (streaming) transcription.

Wispr streams 40 ms packets over gRPC while you talk, so the server has nearly
everything transcribed when you release the key. StreamingSession does the local
equivalent: it cuts the recording at pauses and transcribes finished phrases in the
background. While the current phrase is still open it is transcribed speculatively
whenever the CPU is free; if nothing but silence follows that speculation when you
release, its result is used directly and there is no tail to wait for.

Multilingual: the language is detected once per dictation, choosing only among the
user's dictation languages (Wispr's "Dictation Languages" setting), then fixed for the
rest of that dictation.
"""

import os
import queue
import re
import threading
import time

import numpy as np
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000
BLOCK = 640  # 40 ms
DEFER = object()  # "don't transcribe speculatively yet"


SCRIPTS = {"he": re.compile(r"[֐-׿]"), "ru": re.compile(r"[Ѐ-ӿ]"),
           "uk": re.compile(r"[Ѐ-ӿ]"), "ar": re.compile(r"[؀-ۿ]")}
LATIN = re.compile(r"[A-Za-z]")


def words_for_language(words, language):
    """Keep dictionary hints written in the dictation language's script, so English
    names don't push Hebrew/Russian speech into transliteration (and vice versa)."""
    script = SCRIPTS.get(language)
    if script is None:
        return [w for w in words if LATIN.search(w) or not any(s.search(w) for s in SCRIPTS.values())]
    return [w for w in words if script.search(w)]


class LocalWhisper:
    def __init__(self, model="small", device="cpu", compute_type="int8",
                 cpu_threads=min(8, os.cpu_count() or 4)):
        self.model = WhisperModel(model, device=device, compute_type=compute_type,
                                  cpu_threads=cpu_threads, local_files_only=True)
        self.english_only = model.endswith(".en")
        self.lock = threading.Lock()
        # Language ID with the tiny model: ~0.2 s vs ~3 s for a full encoder pass of "small"
        # on a laptop CPU, and just as accurate from ~2 s of speech.
        self.detector = None
        if not self.english_only and model not in ("tiny", "base"):
            try:
                self.detector = WhisperModel("tiny", device=device, compute_type=compute_type,
                                             cpu_threads=cpu_threads, local_files_only=True)
            except Exception:
                self.detector = None

    def detect_language(self, audio, allowed):
        """(language, confidence) — the most likely of `allowed` ISO codes (all if empty).

        Confidence is renormalized over the allowed set. Whisper is unreliable on ~1 s
        clips (Hebrew read as English 0.50 vs 0.12), so callers wait for ~2 s of speech.
        """
        if self.english_only:
            return "en", 1.0
        if len(allowed) == 1:
            return allowed[0], 1.0
        try:
            if self.detector is not None:
                _, _, probs = self.detector.detect_language(audio)
            else:
                with self.lock:
                    _, _, probs = self.model.detect_language(audio)
        except Exception:
            return (allowed[0] if allowed else None), 0.0
        scores = dict(probs)
        pool = allowed or list(scores)
        best = max(pool, key=lambda code: scores.get(code, 0.0))
        total = sum(scores.get(code, 0.0) for code in pool) or 1.0
        return best, scores.get(best, 0.0) / total

    rtf = 0.0  # measured seconds of compute per second of audio (moving average)

    def transcribe(self, audio, language=None, prompt=None):
        start = time.perf_counter()
        try:
            return self._transcribe(audio, language, prompt)
        finally:
            if audio.size >= SAMPLE_RATE:
                ratio = (time.perf_counter() - start) / (audio.size / SAMPLE_RATE)
                self.rtf = ratio if not self.rtf else 0.7 * self.rtf + 0.3 * ratio

    def _transcribe(self, audio, language=None, prompt=None):
        with self.lock:
            segments, info = self.model.transcribe(
                audio,
                language=language,
                initial_prompt=prompt or None,
                beam_size=5,
                vad_filter=True,
                condition_on_previous_text=False,
                without_timestamps=True,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
        return text, info.language


class StreamingSession:
    """One dictation. feed() 40 ms int16 blocks from the audio thread; finish() on release."""

    def __init__(self, asr, language=None, vocabulary=(), pause_ms=550, min_segment_s=1.2,
                 max_segment_s=20.0, languages=()):
        self.asr = asr
        self.languages = list(languages)
        self.language = language or ("en" if asr_english_only(asr) else None)
        self.vocabulary = list(vocabulary)
        self.pause_blocks = pause_ms // 40
        self.min_blocks = int(min_segment_s * 1000 / 40)
        self.max_blocks = int(max_segment_s * 1000 / 40)
        self.blocks = []          # all float32 blocks so far
        self.levels = []          # dBFS per block
        self.seg_start = 0        # first block not yet submitted
        self.silent_run = 0
        self.noise_floor = -50.0
        self.committed = []       # texts of finished segments, in order
        self.detected_language = None
        self._spec = None         # (start_block, end_block, text) for the open phrase
        self.last_voice = 0       # block index just after the last non-silent block
        self._finishing = False
        self._pending = 0         # submitted segments not yet appended to committed
        self.used_speculation = False
        self.slow = getattr(asr, "rtf", 0.0) > 0.33
        self._jobs = queue.Queue()
        self._done = threading.Event()
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    # --- called from the audio callback thread: keep it cheap ---
    def feed(self, block_int16):
        block = block_int16.astype(np.float32) / 32768.0
        level = 20 * np.log10(max(float(np.sqrt(np.mean(block * block))), 1e-10))
        self.blocks.append(block)
        self.levels.append(level)
        # Track a slowly adapting noise floor; "silence" is anything near it.
        if level < self.noise_floor + 6:
            self.noise_floor = 0.95 * self.noise_floor + 0.05 * level
            self.silent_run += 1
        else:
            self.silent_run = 0
            self.last_voice = len(self.blocks)
        pending = len(self.blocks) - self.seg_start
        if pending >= self.min_blocks and self.silent_run >= self.pause_blocks:
            self._submit(len(self.blocks) - self.silent_run // 2)
        elif pending >= self.max_blocks:
            window = self.levels[self.seg_start + self.min_blocks:]
            quietest = self.seg_start + self.min_blocks + int(np.argmin(window))
            self._submit(quietest)

    def _submit(self, end):
        start = self.seg_start
        if end <= start:
            return
        self.seg_start = end
        self._pending += 1
        # Resolved on the worker, after any in-flight speculation has finished.
        self._jobs.put((start, end, min(self.last_voice, end)))

    # --- background ASR worker ---
    def _run(self):
        while True:
            try:
                job = self._jobs.get(timeout=0.1)
            except queue.Empty:
                try:
                    self._speculate()
                except Exception as e:
                    print(f"  [asr] speculation failed: {e!r}")
                continue
            if job is None:
                break
            try:
                self._run_segment(*job)
            except Exception as e:  # never leave finish() waiting on a dead worker
                print(f"  [asr] segment failed: {e!r}")
            finally:
                self._pending -= 1
        self._done.set()

    def _run_segment(self, start, end, voice_end):
        spec = self._spec
        if spec and spec[0] == start and spec[2] and spec[1] >= voice_end:
            # A speculation already transcribed every voiced block of this segment.
            self.used_speculation = True
            self.committed.append(spec[2])
            return
        audio = np.concatenate(self.blocks[start:end])
        if _is_speech(audio):
            text, lang = self.asr.transcribe(audio, self._language_for(audio, final=True), self._prompt())
            if text:
                self.committed.append(text)
                self.detected_language = self.detected_language or lang

    def _speculate(self):
        start, end = self.seg_start, len(self.blocks)
        if self._finishing or end - start < 25:
            return  # less than 1 s of open phrase
        spec = self._spec if self._spec and self._spec[0] == start else None
        if spec and spec[1] >= self.last_voice:
            return  # already covers all speech so far
        if self.silent_run < 5 and (self.slow or (spec and end - spec[1] < 12)):
            # Only speculate at a pause (>= 200 ms) when the model is slower than ~3x real time
            # (e.g. "small" on a laptop CPU), otherwise every 0.5 s of new audio.
            return
        audio = np.concatenate(self.blocks[start:end])
        if not _is_speech(audio):
            return
        language = self._language_for(audio, final=False)
        if language is DEFER:
            return  # not enough speech yet to tell the language reliably
        text, lang = self.asr.transcribe(audio, language, self._prompt())
        self._spec = (start, end, text)
        self.detected_language = self.detected_language or lang

    def _language_for(self, audio, final):
        """Detect among the allowed languages, then keep it for the rest of the dictation.

        Speculative passes wait for 2 s of audio; the language is locked once detection is
        confident (>= 0.6 among the allowed set) or 3 s of audio were heard.
        """
        if self.language is not None:
            return self.language
        detect = getattr(self.asr, "detect_language", None)
        if detect is None:
            return None
        if not final and audio.size < 2 * SAMPLE_RATE:
            return DEFER
        lang, confidence = detect(audio, self.languages)
        if confidence >= 0.6 or audio.size >= 3 * SAMPLE_RATE:
            self.language = lang
        return lang

    def _prompt(self):
        # Vocabulary + the last committed words keep spelling/context consistent across cuts.
        parts = []
        vocab = words_for_language(self.vocabulary, self.language) if self.language else []
        if vocab:
            parts.append(", ".join(vocab) + ".")
        if self.committed:
            parts.append(" ".join(self.committed)[-200:])
        return " ".join(parts)

    def partial_text(self):
        return " ".join(self.committed)

    def text_if_finished_now(self):
        """Full transcript if nothing is left to transcribe (all segments done and a
        speculation covers every voiced block), else None. Used to start formatting early."""
        if self._pending:
            return None
        spec = self._spec
        if self.seg_start >= self.last_voice:
            return " ".join(self.committed).strip() or None
        if spec and spec[0] == self.seg_start and spec[2] and spec[1] >= self.last_voice:
            return " ".join(self.committed + [spec[2]]).strip()
        return None

    def finish(self):
        """Transcribe the remaining tail and return (full_text, language)."""
        self._finishing = True
        self._submit(len(self.blocks))
        self._jobs.put(None)
        self._done.wait()
        return " ".join(self.committed).strip(), self.language or self.detected_language

    def cancel(self):
        self._finishing = True
        self._jobs.put(None)

    def audio(self):
        return np.concatenate(self.blocks) if self.blocks else np.zeros(0, dtype=np.float32)

    def duration_ms(self):
        return len(self.blocks) * 40

    def speech_ms(self):
        """Time with voice in it (Wispr's speechDuration, used for WPM)."""
        return sum(1 for lv in self.levels if lv >= self.noise_floor + 6) * 40


def asr_english_only(asr):
    return getattr(asr, "english_only", False)


def _is_speech(audio, threshold_dbfs=-50.0):
    rms = float(np.sqrt(np.mean(audio * audio))) if audio.size else 0.0
    return 20 * np.log10(max(rms, 1e-10)) > threshold_dbfs and audio.size >= SAMPLE_RATE // 4
