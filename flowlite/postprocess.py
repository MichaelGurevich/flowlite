"""Client-side post-processing, in Wispr's order (main/index.js ~4193000-4205000):

1. snippets + dictionary replacements
2. trailing-period removal for casual styles / short messages
3. context-aware casing and spacing against the current line before/after the cursor
4. "press enter" voice command and the all-lowercase format
"""

import re

PRESS_ENTER = re.compile(r"([.!?;])?\s*\bpress enter\s*([.!?,;:-]*)\s*$", re.IGNORECASE)
CONTINUE_SKIP = "—`,-/:;()[]{} \t"
LEADING_SPACE_AFTER = set("!%),.:;>?]}")
STRIP_BEFORE = set("!%,.:;>?")


def strip_press_enter(text, raw_asr=""):
    """Return (text_without_command, should_press_enter)."""
    if PRESS_ENTER.search(text):
        return PRESS_ENTER.sub(lambda m: m.group(1) or "", text).rstrip(), True
    if PRESS_ENTER.search(raw_asr):  # the formatter may have dropped the phrase
        return text, True
    return text, False


def _sentences(text):
    return len([s for s in re.split(r"[.!?]+\s", text.strip()) if s])


def trailing_period(text, style, app_type, line_before="", line_after=""):
    if not text.endswith("."):
        return text
    if re.search(r"[.!?]", line_before + line_after):
        return text  # the surrounding line already uses sentence punctuation
    n = _sentences(text)
    strip = (style == "very_casual"
             or (style == "casual" and n <= 10)
             or (style == "default" and app_type == "messaging" and n <= 2))
    return text[:-1] if strip else text


def fit_to_context(text, line_before="", line_after=""):
    if not text:
        return text
    before = line_before.rstrip(CONTINUE_SKIP)
    if before and before[-1].isalnum() and text[0].isupper() and not _keeps_capital(text):
        text = text[0].lower() + text[1:]
    if line_after and (line_after[0].islower() or line_after[0] in STRIP_BEFORE):
        text = text.rstrip(".!?")
    if line_before and (line_before[-1].isalnum() or line_before[-1] in LEADING_SPACE_AFTER):
        text = " " + text
    if not line_after or line_after[0].isalnum():
        text = text + " "
    return text


def _keeps_capital(text):
    first = re.split(r"[\s,.!?;:]", text, maxsplit=1)[0]
    return first == "I" or first.startswith("I'") or (len(first) > 1 and first[1:].lower() != first[1:])


def run(text, settings, app_type, style, ctx, raw_asr=""):
    """Steps 2-4. Returns (text, press_enter)."""
    press_enter = False
    if settings.press_enter_command:
        text, press_enter = strip_press_enter(text, raw_asr)
    text = trailing_period(text, style, app_type, ctx.line_before, ctx.line_after)
    if settings.all_lowercase:
        text = text.lower()
    text = fit_to_context(text, ctx.line_before, ctx.line_after)
    return text, press_enter
