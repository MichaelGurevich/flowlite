"""Rule-based transcript cleanup. Always runs; the local LLM formatter builds on it."""

import re

FILLER_WORDS = {"um", "umm", "uh", "uhh", "erm", "hmm", "mm"}
FILLERS = re.compile(r"(?<!\w)(?:u+m+|u+h+|e+r+m+|h+m+)(?!\w)[,.]?\s*", re.IGNORECASE)


def rule_based(text):
    text = FILLERS.sub("", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"[,;:]\s*(?=[,.!?;:])", "", text)  # "thinking, , we" -> "thinking, we"
    text = re.sub(r"\s{2,}", " ", text).strip()
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text

