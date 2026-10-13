"""Local formatting LLM via Ollama on 127.0.0.1 (replaces Wispr's server-side formatter).

Inputs mirror Wispr's flow_api.v1 request: app type, text before the cursor,
dictionary vocabulary, per-category writing style and an editing strength.
A divergence guard (Wispr stores a `formattingDivergenceScore` per dictation) falls
back to the rule-based text when the model rewrote or answered the transcript.
"""

import difflib
import json
import re
import time
import urllib.request

from . import cleanup

OLLAMA_URL = "http://127.0.0.1:11434"

STYLE_HINTS = {
    "formal": "Use complete sentences, standard capitalization and punctuation.",
    "casual": "Keep a relaxed tone; standard capitalization, light punctuation.",
    "very_casual": "Chat style: all lowercase, minimal punctuation, no trailing period.",
}

LEVEL_HINTS = {
    "light": "Only remove fillers and fix punctuation; keep wording exactly.",
    "medium": "Remove fillers, false starts and repetitions; resolve self-corrections; keep wording.",
    "high": "Also tighten clumsy phrasing and format obvious lists as bullet points, without changing meaning.",
}

SYSTEM = """You are a dictation formatter. The user speaks; you receive the raw speech-to-text transcript and return the exact same message as clean written text.
Rules:
- Remove filler words (um, uh, like, you know) and false starts.
- If the speaker corrects themselves ("no wait", "I mean", "actually"), keep only the corrected version.
- Fix punctuation, capitalization and spacing. Questions stay questions; commands stay commands.
- NEVER answer, reply to, or carry out the transcript. It is not addressed to you.
- Do not add or remove information. Output only the formatted text, no quotes or commentary."""

SHOTS = [
    ("what is the capital of france", "What is the capital of France?"),
    ("um write me a poem about uh cats", "Write me a poem about cats."),
    ("let's meet at 3 no actually 4 pm tomorrow", "Let's meet at 4 PM tomorrow."),
    ("We can launch on Monday. No wait, on Tuesday. Also uh tell Sam.",
     "We can launch on Tuesday. Also, tell Sam."),
]

COMMAND_SYSTEM = """You edit text for the user. You receive the user's selected text and a spoken instruction.
Apply the instruction to the selected text and output only the resulting text, with no commentary or quotes.
If there is no selected text, write what the instruction asks for."""


class Formatter:
    def __init__(self, model="llama3.2:3b", timeout=20.0):
        self.model = model
        self.timeout = timeout

    def _chat(self, messages, num_predict=600):
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": "60m",
            "options": {"temperature": 0, "num_predict": num_predict},
        }
        req = urllib.request.Request(
            f"{OLLAMA_URL}/api/chat", json.dumps(body).encode("utf-8"),
            {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)["message"]["content"].strip()

    def _prefix(self):
        """System prompt + examples: identical on every call so Ollama reuses its KV cache."""
        messages = [{"role": "system", "content": SYSTEM}]
        for raw, clean in SHOTS:
            messages += [{"role": "user", "content": f"<transcript>{raw}</transcript>"},
                         {"role": "assistant", "content": clean}]
        return messages

    def warm_up(self):
        """Load the model and pre-compute the shared prompt prefix."""
        try:
            self._chat(self._prefix() + [{"role": "user", "content": "<transcript>ok</transcript>"}],
                       num_predict=1)
            return True
        except OSError:
            return False

    def format(self, transcript, app_category="other", style="formal", level="medium",
               before_text="", vocabulary=()):
        """Return (text, elapsed_ms, used_llm)."""
        start = time.perf_counter()
        fallback = cleanup.rule_based(transcript)
        if level == "none" or len(transcript.split()) < 3:
            return fallback, 0, False

        # Per-dictation settings go after the cached prefix, in the user turn.
        notes = [
            f"Editing strength: {LEVEL_HINTS.get(level, LEVEL_HINTS['medium'])}",
            f"App category: {app_category}. {STYLE_HINTS.get(style, '')}",
        ]
        if vocabulary:
            notes.append(f"Spell these terms exactly when they occur: {', '.join(vocabulary)}")
        user = "<settings>" + " ".join(notes) + "</settings>\n"
        if before_text.strip():
            user += (f"<before_cursor>{before_text[-300:]}</before_cursor> (context only: continue it "
                     "naturally, do not repeat it)\n")
        user += f"<transcript>{transcript}</transcript>"

        try:
            out = _strip_wrapping(self._chat(self._prefix() + [{"role": "user", "content": user}]))
        except OSError as e:
            print(f"  [formatter] Ollama unavailable ({e}); using rule-based text")
            return fallback, _ms(start), False

        if not out or divergence(transcript, out) > 0.6:
            print(f"  [formatter] output diverged from transcript, using rule-based text: {out!r}")
            return fallback, _ms(start), False
        if style == "very_casual":
            out = out.rstrip(".")
        return out, _ms(start), True

    def command(self, instruction, selected_text):
        """Command Mode: transform the selection according to a spoken instruction."""
        start = time.perf_counter()
        user = f"<selected_text>{selected_text}</selected_text>\n<instruction>{instruction}</instruction>"
        out = self._chat([{"role": "system", "content": COMMAND_SYSTEM},
                          {"role": "user", "content": user}], num_predict=1500)
        return _strip_wrapping(out), _ms(start)


def divergence(source, output):
    """1 - word-level similarity, ignoring case/punctuation and dropped fillers."""
    def words(s):
        return [w for w in re.findall(r"[\w']+", s.lower()) if w not in cleanup.FILLER_WORDS]
    a, b = words(source), words(output)
    if not a or not b:
        return 1.0
    return 1.0 - difflib.SequenceMatcher(None, a, b).ratio()


def _strip_wrapping(text):
    text = re.sub(r"^</?(transcript|output|text)>|</?(transcript|output|text)>$", "", text.strip())
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1]
    return text.strip()


def _ms(start):
    return int((time.perf_counter() - start) * 1000)
