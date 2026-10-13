"""Import your own local Wispr Flow data into FlowLite (read-only, nothing leaves the PC).

Sources: %APPDATA%\\Wispr Flow\\flow.sqlite (History, Dictionary) and config.json (prefs).
"""

import datetime as dt
import json
import os
import sqlite3
from pathlib import Path

from . import categories

WISPR_DIR = Path(os.environ.get("APPDATA", "")) / "Wispr Flow"
STYLE_MAP = {"formal": "formal", "casual": "casual", "veryCasual": "very_casual", "genz": "very_casual",
             "excited": "excited", "default": "formal"}
CLEANUP_MAP = {"none": "none", "light": "light", "medium": "medium", "high": "high", "full": "high"}


def available():
    return (WISPR_DIR / "flow.sqlite").exists()


def _ts(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value / 1000 if value > 1e12 else value
    text = str(value).replace(" +00:00", "+00:00").replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def _prefs():
    try:
        data = json.loads((WISPR_DIR / "config.json").read_text(encoding="utf-8"))
        return data.get("prefs", {}).get("user", {}) or {}
    except (OSError, ValueError):
        return {}


def import_all(db, settings, history=True, dictionary=True, prefs=True):
    """Returns a summary dict. Safe to run twice: rows already imported are skipped."""
    src = sqlite3.connect(f"file:{WISPR_DIR / 'flow.sqlite'}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    summary = {"history": 0, "words": 0, "snippets": 0, "prefs": False}

    if dictionary:
        existing = {(r["phrase"].lower(), r["is_snippet"]) for r in db.query("select phrase, is_snippet from dictionary")}
        for r in src.execute("select phrase, replacement, isSnippet, source, isStarred, createdAt, modifiedAt"
                             " from Dictionary where isDeleted=0"):
            key = ((r["phrase"] or "").lower(), int(r["isSnippet"] or 0))
            if not r["phrase"] or key in existing:
                continue
            db.insert("dictionary", phrase=r["phrase"], replacement=r["replacement"],
                      is_snippet=key[1], source="learned" if r["source"] == "user_edits" else "manual",
                      starred=int(r["isStarred"] or 0), created=_ts(r["createdAt"]),
                      modified=_ts(r["modifiedAt"]))
            summary["snippets" if key[1] else "words"] += 1

    if history:
        seen = {r["ts"] for r in db.query("select ts from history where source='wispr'")}
        for r in src.execute("select timestamp, asrText, formattedText, editedText, app, url, duration,"
                             " speechDuration, numWords, detectedLanguage, status,"
                             " numDictionaryReplacements from History"):
            ts = _ts(r["timestamp"])
            if ts is None or ts in seen or r["status"] in ("dismissed", "empty"):
                continue
            text = r["formattedText"] or r["asrText"] or ""
            if not text.strip():
                continue
            app_type, style_cat = categories.classify(r["app"] or "", r["url"] or "")
            db.insert("history", ts=ts, mode="dictation", app=r["app"], title=r["url"],
                      category=f"{app_type}/{style_cat}", language=r["detectedLanguage"],
                      asr_text=r["asrText"], final_text=text, edited_text=r["editedText"],
                      words=r["numWords"] or len(text.split()),
                      audio_ms=int((r["duration"] or 0) * 1000),
                      speech_ms=int((r["speechDuration"] or 0) * 1000),
                      replacements=r["numDictionaryReplacements"] or 0, status="ok", source="wispr")
            summary["history"] += 1

    if prefs:
        p = _prefs()
        if p.get("firstName"):
            settings.first_name = p["firstName"]
        langs = [code for code in (p.get("selectedLanguages") or []) if isinstance(code, str)]
        if langs:
            settings.languages = langs
        styles = p.get("personalizationStyles") or {}
        for cat in ("personal", "work", "email", "other"):
            if styles.get(cat) in STYLE_MAP:
                settings.styles[cat] = STYLE_MAP[styles[cat]]
        cleanup = (p.get("autoCleanup") or {}).get("level")
        if cleanup in CLEANUP_MAP:
            settings.cleanup_level = CLEANUP_MAP[cleanup]
        for ours, theirs in (("sounds", "enableSounds"), ("mute_media", "shouldMuteAudio"),
                             ("learn_from_edits", "shouldAutoLearnWords"), ("read_context", "useAxContext"),
                             ("press_enter_command", "pressEnterCommandEnabled")):
            if isinstance(p.get(theirs), bool):
                setattr(settings, ours, p[theirs])
        settings.save()
        summary["prefs"] = True
    src.close()
    return summary
