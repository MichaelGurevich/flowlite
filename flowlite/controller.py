"""Dictation state machine (Wispr: status idle/listening/processing + isLocked).

Gestures, following Wispr's Windows behavior:
- push_to_talk down: start. Released >= 500 ms after start: stop and transcribe.
  Released < 500 ms after start: wait 500 ms for a second press; none -> dismiss
  ("hold the keys" hint). Second press within 500 ms of start -> hands-free lock.
- Locked: the next push_to_talk / hands_free press stops (within 500 ms of start: dismiss).
- hands_free: press to start locked, press again to stop. Adding Space while holding
  push_to_talk locks.
- command_mode: hold like push-to-talk; adding Alt during push-to-talk upgrades to it.
- dismiss (Esc) cancels. paste_last / copy_last fire once every key is released (+25 ms).
- transform_1 / transform_2 (Win+Alt+1/2): rewrite the selected text with a Transform,
  also once every key is released.
"""

import concurrent.futures
import threading
import time

from . import categories, cleanup, context, insert, learn, postprocess, sounds, win32
from .asr import StreamingSession

DEBOUNCE_S = 0.5
MILESTONES = (100, 500, 1000, 2000, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000)


class Controller:
    def __init__(self, settings, asr, formatter, dictionary, history, recorder, overlay, muter):
        self.s = settings
        self.asr = asr
        self.formatter = formatter
        self.dictionary = dictionary
        self.history = history
        self.recorder = recorder
        self.overlay = overlay
        self.muter = muter
        self.observer = learn.EditObserver(self._on_edit_observed)

        self.lock = threading.RLock()
        self.state = "idle"            # idle | listening | processing
        self.mode = None               # ptt | popo | command
        self.locked = False
        self.started_at = 0.0
        self.session = None
        self.ctx_slot = None
        self.release_timer = None
        self.duration_timers = []
        self.pending_action = None
        self.control = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="control")
        self.worker = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="pipeline")
        self.prefetch = concurrent.futures.ThreadPoolExecutor(1, thread_name_prefix="prefetch")
        self.prefetched = {}  # raw transcript -> Future of formatter.format(...)
        self.on_history_changed = None   # callback() -> refresh the hub
        self.last_text_memory = None     # paste-last works even when history isn't stored

        self._floor = -60.0
        self._level_sum = 0.0
        self._level_n = 0
        self._level_sent = 0.0
        recorder.on_level = self._on_level

    # ------------------------------------------------------------------ hotkeys
    def on_hotkey(self, kind, name):
        with self.lock:
            if kind == "down":
                self._on_down(name)
            elif kind == "up":
                self._on_up(name)
            elif kind == "all_up" and self.pending_action:
                action, self.pending_action = self.pending_action, None
                threading.Timer(0.025, self._run_action, args=(action,)).start()

    def _on_down(self, name):
        now = time.monotonic()
        dt = now - self.started_at
        masked = ("push_to_talk", "hands_free", "command_mode", "transform_1", "transform_2")
        if name in masked and _has_masked_key(self.s.shortcuts.get(name, "")):
            self.control.submit(win32.send_mask_key)

        if name == "push_to_talk":
            if self.state == "processing":
                self.overlay.flash("Still transcribing the last dictation…")
            elif self.state == "idle":
                self._start("ptt")
            elif self.locked:
                self._dismiss("triple_press") if dt < DEBOUNCE_S else self._stop()
            elif dt < DEBOUNCE_S:
                self._lock()
        elif name == "hands_free":
            if self.state == "processing":
                self.overlay.flash("Still transcribing the last dictation…")
            elif self.state == "idle":
                self._start("popo")
            elif self.locked:
                self._dismiss("debounce_popo") if dt < DEBOUNCE_S else self._stop()
            else:
                self._lock()
        elif name == "command_mode":
            if not self.s.command_mode_enabled:
                return
            if self.state == "idle":
                self._start("command")
            elif self.state == "listening" and not self.locked and self.mode == "ptt":
                self.mode = "command"
                self.overlay.set_state("command")
        elif name == "dismiss":
            if self.state == "listening":
                self._dismiss("escape")
        elif name in ("paste_last", "copy_last", "transform_1", "transform_2"):
            if self.state == "listening" and not self.locked and dt < 1.0:
                self._dismiss("other_shortcut")
            if self.state == "idle":
                self.pending_action = name

    def _on_up(self, name):
        if self.state != "listening" or self.locked:
            return
        holds = (name == "push_to_talk" and self.mode in ("ptt", "command")) or \
                (name == "command_mode" and self.mode == "command")
        if not holds:
            return
        if time.monotonic() - self.started_at >= DEBOUNCE_S:
            self._stop()
            return
        started = self.started_at

        def debounce():
            with self.lock:
                if self.state == "listening" and not self.locked and self.started_at == started:
                    self._dismiss("debounce_ptt")
                    keys = self.s.shortcuts["push_to_talk"].replace("+", " + ").title()
                    self.overlay.flash(f"Hold {keys} while you talk, or double-tap for hands-free")
        self.release_timer = threading.Timer(DEBOUNCE_S, debounce)
        self.release_timer.start()

    # ---------------------------------------------------------------- lifecycle
    def start_hands_free(self):
        with self.lock:
            if self.state == "idle":
                self._start("popo")
            elif self.state == "listening":
                self._stop()

    def cancel(self):
        with self.lock:
            if self.state == "listening":
                self._dismiss("cancel_button")

    def _start(self, mode):
        self.state, self.mode = "listening", mode
        self.locked = mode == "popo"
        self.started_at = time.monotonic()
        self._floor = -20.0  # adaptive noise floor restarts each dictation
        self.observer.cancel()
        languages = [] if self.s.auto_detect_all else list(self.s.languages)
        self.session = StreamingSession(self.asr, self.s.language or None, self.dictionary.all_words(),
                                        languages=languages)
        self.ctx_slot = slot = {"ready": threading.Event()}
        threading.Thread(target=self._capture_context, args=(slot,), daemon=True).start()
        session = self.session
        self.prefetched = {}
        self.control.submit(self.recorder.start, session.feed)
        if mode != "command":
            threading.Thread(target=self._prefetch_loop, args=(session, slot), daemon=True).start()
        sounds.play(sounds.LOCK if self.locked else sounds.START, self.s.sounds)
        self.muter.mute()
        self.overlay.set_state({"ptt": "listening", "popo": "locked", "command": "command"}[mode])
        limit = self.s.max_dictation_min * 60
        self.duration_timers = [
            threading.Timer(limit - 60, self.overlay.flash, args=("Dictation will stop in 1 minute", 5)),
            threading.Timer(limit, self._force_stop, args=(self.started_at,)),
        ]
        for t in self.duration_timers:
            t.daemon = True
            t.start()

    def _capture_context(self, slot):
        try:
            slot["ctx"] = context.capture(read_textbox=self.s.read_context)
        finally:
            slot["ready"].set()

    def _lock(self):
        self.locked = True
        if self.mode == "ptt":
            self.mode = "popo"
        if self.release_timer:
            self.release_timer.cancel()
        sounds.play(sounds.LOCK, self.s.sounds)
        self.overlay.set_state("locked" if self.mode == "popo" else "command")

    def _end_recording(self):
        for t in self.duration_timers:
            t.cancel()
        if self.release_timer:
            self.release_timer.cancel()
        self.control.submit(self.recorder.stop)
        self.muter.unmute()

    def _stop(self):
        self.state = "processing"
        self._end_recording()
        sounds.play(sounds.STOP, self.s.sounds)
        self.overlay.set_state("processing")
        session, slot, mode = self.session, self.ctx_slot, self.mode
        released_at = time.perf_counter()
        # The control queue runs recorder.stop before the pipeline reads the session.
        self.control.submit(lambda: self.worker.submit(self._process, session, slot, mode, released_at))

    def _force_stop(self, started_at):
        with self.lock:
            if self.state == "listening" and self.started_at == started_at:
                self._stop()

    def _dismiss(self, reason):
        self._end_recording()
        if self.session:
            self.session.cancel()
        self.state, self.mode, self.locked = "idle", None, False
        sounds.play(sounds.CANCEL, self.s.sounds)
        self.overlay.set_state("idle")
        print(f"  dismissed ({reason})")

    def _finish(self, error=False):
        with self.lock:
            self.state, self.mode, self.locked = "idle", None, False
        self.overlay.set_state("error" if error else "idle")
        if error:
            threading.Timer(1.5, lambda: self.state == "idle" and self.overlay.set_state("idle")).start()

    # ----------------------------------------------------------------- prefetch
    def _prefetch_loop(self, session, slot):
        """While the speaker pauses, format the transcript-so-far ahead of the key release.

        Wispr hides formatting latency server-side; locally the LLM is the slowest step,
        so it starts as soon as the transcript is complete and the speaker is quiet.
        """
        while self.session is session and self.state == "listening":
            time.sleep(0.15)
            if session.silent_run < 8 or not slot["ready"].is_set():
                continue  # speaker hasn't paused for 320 ms yet
            raw = session.text_if_finished_now()
            if raw and raw not in self.prefetched:
                ctx = slot.get("ctx") or context.DictationContext()
                self.prefetched[raw] = self.prefetch.submit(self._format, raw, ctx, session.language)

    def _format(self, raw, ctx, language=None):
        app_type, style_cat = categories.classify(ctx.app, ctx.window_title)
        style = self.s.styles.get(style_cat, "formal")
        if language and language != "en":
            # Like Wispr, AI style formatting is English-only; other languages get light cleanup.
            return cleanup.rule_based(raw), 0, False
        text, llm_ms, used = self.formatter.format(
            raw, app_type, style, self.s.cleanup_level, ctx.before_text[-500:],
            self.dictionary.all_words())
        return text, llm_ms, used

    # ----------------------------------------------------------------- pipeline
    def _process(self, session, slot, mode, released_at):
        try:
            raw, lang = session.finish()
            tail_ms = int((time.perf_counter() - released_at) * 1000)
            slot["ready"].wait(1.0)
            ctx = slot.get("ctx") or context.DictationContext()
            if not raw:
                self.overlay.flash("No speech detected", 1.5)
                self._finish()
                return
            if mode == "command":
                self._process_command(raw, ctx, session, released_at, tail_ms)
            else:
                self._process_dictation(raw, ctx, session, released_at, tail_ms, lang)
            self._finish()
        except Exception as e:
            print(f"  error: {e!r}")
            sounds.play(sounds.ERROR, self.s.sounds)
            self._finish(error=True)

    def _process_dictation(self, raw, ctx, session, released_at, tail_ms, lang=None):
        app_type, style_cat = categories.classify(ctx.app, ctx.window_title)
        style = self.s.styles.get(style_cat, "formal")
        snippet = self.dictionary.snippet_for(raw)
        llm_ms, used_llm = 0, False
        if snippet is not None:
            text = snippet
        else:
            future = self.prefetched.get(raw)
            if future is not None:
                text, llm_ms, used_llm = future.result()
                print("  (formatting was prefetched during your pause)")
            else:
                text, llm_ms, used_llm = self._format(raw, ctx, lang)
        text, replacements = self.dictionary.apply_count(text)
        if self.s.auto_transform and snippet is None:
            from . import transforms_engine
            text = transforms_engine.auto_apply(self.s, self.history.db, self.formatter, text)
        text, press_enter = postprocess.run(text, self.s, app_type, style, ctx, raw)

        insert.insert_text(text, mode=self.s.insert_mode)
        if press_enter:
            time.sleep(0.05)
            win32.send_key(win32.VK_RETURN)
        total_ms = int((time.perf_counter() - released_at) * 1000)

        print(f"  [{ctx.app or '?'} · {app_type}/{style}] {text.strip()!r}")
        print(f"  audio {session.duration_ms()} ms | tail asr {tail_ms} ms | llm {llm_ms} ms"
              f" | release→insert {total_ms} ms")
        self.last_text_memory = text.strip()
        row_id = self._store(
            mode="dictation", app=ctx.app, title=ctx.window_title, category=f"{app_type}/{style_cat}",
            language=lang, asr_text=raw, final_text=text.strip(), audio_ms=session.duration_ms(),
            speech_ms=session.speech_ms(), tail_ms=tail_ms, llm_ms=llm_ms, total_ms=total_ms,
            used_llm=int(used_llm), replacements=replacements,
            audio=_wav_bytes(session.audio()) if self.s.save_audio else None)
        if row_id and self.s.learn_from_edits and ctx.element_key is not None:
            self.observer.watch(row_id, ctx, text)

    def _process_command(self, instruction, ctx, session, released_at, tail_ms):
        selected = ctx.selected_text or insert.selected_text_via_copy()
        print(f"  [command] {instruction!r} on {len(selected)} selected chars")
        result, llm_ms = self.formatter.command(instruction, selected)
        if not result:
            self.overlay.flash("Command produced no text", 2)
            return
        insert.insert_text(result, mode=self.s.insert_mode)
        total_ms = int((time.perf_counter() - released_at) * 1000)
        print(f"  llm {llm_ms} ms | release→insert {total_ms} ms")
        self._store(mode="command", app=ctx.app, title=ctx.window_title, category="command/other",
                    asr_text=instruction, final_text=result, audio_ms=session.duration_ms(),
                    speech_ms=session.speech_ms(), tail_ms=tail_ms, llm_ms=llm_ms, total_ms=total_ms,
                    used_llm=1)

    # ------------------------------------------------------------------ storage
    def _store(self, **row):
        """Save a dictation per the Data & Privacy policy, then notify the hub and milestones."""
        policy = self.s.local_storage
        if policy == "never":
            return None
        before = self._total_words()
        row_id = self.history.add(**row)
        if policy == "auto_delete_24h":
            self.history.purge_older_than(24 * 3600)
        after = self._total_words()
        if self.s.notify_milestones:
            for m in MILESTONES:
                if before < m <= after:
                    self.overlay.flash(f"{m:,} words dictated", 4,
                                       "Nice work. That's typing you didn't have to do.")
        if self.on_history_changed:
            self.on_history_changed()
        return row_id

    def _total_words(self):
        rows = self.history.db.query("select coalesce(sum(words),0) w from history where status='ok'")
        return rows[0]["w"]

    # --------------------------------------------------------------- transforms
    def _run_transform_shortcut(self, slot):
        """Win+Alt+1/2: rewrite the selection in the focused app with that slot's Transform."""
        from . import transforms_engine
        with self.lock:
            if self.state != "idle":
                return
            self.state = "processing"
        self.overlay.set_state("processing")
        try:
            ok, message = transforms_engine.transform_selection(
                self.formatter, self.history.db, slot, insert_mode=self.s.insert_mode)
        finally:
            self._finish()
        self.overlay.flash(message, 1.6 if ok else 2.5)

    # -------------------------------------------------------------------- retry
    def retry(self, history_id):
        """Re-transcribe a saved recording (Home -> Retry transcript). Returns new text or None."""
        row = self.history.get(history_id)
        if not row or not row.get("audio"):
            return None
        import io
        import wave
        import numpy as np
        with wave.open(io.BytesIO(row["audio"])) as w:
            audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        languages = [] if self.s.auto_detect_all else list(self.s.languages)
        lang = self.asr.detect_language(audio, languages)[0] if hasattr(self.asr, "detect_language") else None
        raw, _ = self.asr.transcribe(audio, lang, None)
        if not raw:
            return None
        text, _, used = self._format(raw, context.DictationContext(app=row.get("app") or ""), lang)
        text = self.dictionary.apply(text)
        self.history.db.update("history", history_id, asr_text=raw, final_text=text, language=lang,
                               words=len(text.split()), used_llm=int(used))
        if self.on_history_changed:
            self.on_history_changed()
        return text

    def _run_action(self, action):
        if action.startswith("transform_"):
            self._run_transform_shortcut(action)
            return
        text = self.history.last_text() or self.last_text_memory
        if not text:
            self.overlay.flash("Nothing dictated yet", 1.5)
            return
        if action == "paste_last":
            insert.insert_text(text, mode=self.s.insert_mode)
        else:
            win32.set_clipboard_text(text)
            self.overlay.flash("Copied last transcript", 1.5)

    def _on_edit_observed(self, history_id, pasted, edited):
        self.history.set_edited(history_id, edited)
        for word in learn.candidates(pasted, edited, self.dictionary.all_words(10000)):
            if self.dictionary.learn(word):
                print(f"  learned: {word}")
                self.overlay.flash(f"Added “{word}” to your dictionary", 3)

    # ------------------------------------------------------------------- levels
    def _on_level(self, dbfs):
        # Wispr: adaptive floor (min seen, bounded at -60 dB), level = clamp((dB-floor)/20),
        # averaged and sent every 150 ms.
        self._floor = max(-60.0, min(self._floor, dbfs))
        self._level_sum += min(1.0, max(0.0, (dbfs - self._floor) / 20))
        self._level_n += 1
        now = time.monotonic()
        if now - self._level_sent >= 0.15:
            self.overlay.set_level(self._level_sum / self._level_n)
            self._level_sum, self._level_n, self._level_sent = 0.0, 0, now


def _has_masked_key(shortcut):
    keys = {k.strip().lower() for k in shortcut.split("+")}
    return bool(keys & {"win", "alt", "cmd"})


def _wav_bytes(audio):
    import io
    import wave
    import numpy as np
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())
    return buf.getvalue()
