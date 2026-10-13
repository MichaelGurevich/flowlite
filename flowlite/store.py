"""Local settings and database (Wispr: electron-store prefs + flow.sqlite).

Everything lives in %APPDATA%\\FlowLite: settings.json and flowlite.sqlite
(history, dictionary + snippets, scratchpad notes, transforms).
"""

import datetime as dt
import json
import os
import sqlite3
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "FlowLite"
DB_PATH = DATA_DIR / "flowlite.sqlite"


def _windows_display_name():
    try:
        import ctypes
        size = ctypes.c_ulong(256)
        buf = ctypes.create_unicode_buffer(256)
        if ctypes.windll.secur32.GetUserNameExW(3, buf, ctypes.byref(size)) and buf.value:  # NameDisplay
            return buf.value.split()[0]
    except Exception:
        pass
    return os.environ.get("USERNAME", "").capitalize()


@dataclass
class Settings:
    # Shortcuts: "+"-joined key names (ctrl, win, alt, shift, space, esc, a-z, 0-9, f1-f24).
    # Defaults are Wispr Flow's Windows defaults.
    shortcuts: dict = field(default_factory=lambda: {
        "push_to_talk": "ctrl+win",          # hold; double-tap within 500 ms locks hands-free
        "hands_free": "ctrl+win+space",      # press to start, press again to stop
        "command_mode": "ctrl+win+alt",      # hold, speak an instruction for the selected text
        "paste_last": "shift+alt+z",
        "copy_last": "shift+alt+x",
        "transform_1": "win+alt+1",
        "transform_2": "win+alt+2",
        "dismiss": "esc",
    })
    first_name: str = field(default_factory=_windows_display_name)
    whisper_model: str = "small"       # multilingual; "base" is faster, "small.en" English-only
    languages: list = field(default_factory=lambda: ["en", "he", "ru"])
    auto_detect_all: bool = False      # detect among all 99 languages instead of `languages`
    language: str = ""                 # legacy single-language override
    llm_model: str = "llama3.2:3b"
    cleanup_level: str = "light"       # none | light | medium | high  (Wispr default: light)
    styles: dict = field(default_factory=lambda: {   # formal | casual | very_casual | excited
        "personal": "casual", "work": "formal", "email": "formal", "other": "formal"})
    theme: str = "light"
    read_context: bool = True          # Data & Privacy -> Context awareness
    learn_from_edits: bool = True      # System -> Auto-add to dictionary
    command_mode_enabled: bool = True
    press_enter_command: bool = False
    all_lowercase: bool = False
    auto_transform: str = ""           # Transforms -> Auto apply after dictation (transform name)
    sounds: bool = True
    mute_media: bool = True            # Wispr's Windows default
    show_resting_bar: bool = True      # System -> Show Flow Bar at all times
    notify_suggestions: bool = True
    notify_milestones: bool = True
    warm_mic: bool = False
    mic: str = ""
    insert_mode: str = "paste"         # paste | type
    save_audio: bool = True            # keep recordings locally (play / retry from History)
    local_storage: str = "keep"        # keep | auto_delete_24h | never
    max_dictation_min: int = 20
    onboarded: bool = False

    @classmethod
    def load(cls):
        path = DATA_DIR / "settings.json"
        if not path.exists():
            s = cls()
            s.save()
            return s
        data = json.loads(path.read_text(encoding="utf-8"))
        known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
        s = cls(**known)
        s.shortcuts = {**cls().shortcuts, **s.shortcuts}
        s.styles = {**cls().styles, **s.styles}
        if s.whisper_model == "base.en" and "whisper_model" in data and not data.get("_v2"):
            s.whisper_model = "small"  # migrate pre-multilingual default
        return s

    def save(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        data = asdict(self)
        data["_v2"] = True
        (DATA_DIR / "settings.json").write_text(json.dumps(data, indent=2, ensure_ascii=False),
                                                encoding="utf-8")


SCHEMA = """
create table if not exists history (
    id integer primary key, ts real, mode text, app text, title text, category text,
    language text, asr_text text, final_text text, edited_text text, words int default 0,
    audio_ms int, speech_ms int, tail_ms int, llm_ms int, total_ms int, used_llm int,
    replacements int default 0, status text default 'ok', source text default 'flowlite',
    audio blob);
create index if not exists history_ts on history(ts);
create table if not exists dictionary (
    id integer primary key, phrase text not null, replacement text, is_snippet int default 0,
    source text default 'manual', starred int default 0, used int default 0,
    created real, modified real);
create table if not exists notes (
    id integer primary key, title text, content text, created real, modified real,
    pinned int default 0);
create table if not exists transforms (
    id integer primary key, name text, description text, prompt text, shortcut_slot text,
    builtin int default 0, position int default 0);
"""

DEFAULT_TRANSFORMS = [
    ("Polish", "Improve clarity and conciseness",
     "Rewrite the text to be clearer and more concise. Fix grammar and flow. Keep the meaning, "
     "language and tone. Output only the rewritten text.", "transform_1", 1, 0),
    ("Prompt Engineer", "Constructs optimal prompts",
     "Turn the text into a clear, well-structured prompt for an AI assistant: state the goal, "
     "context, constraints and desired output format. Output only the prompt.", "transform_2", 1, 1),
]


class Database:
    def __init__(self, path=None):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self.path = Path(path or DB_PATH)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)
            if not self.db.execute("select 1 from transforms limit 1").fetchone():
                self.db.executemany(
                    "insert into transforms (name, description, prompt, shortcut_slot, builtin, position)"
                    " values (?,?,?,?,?,?)", DEFAULT_TRANSFORMS)
            self.db.commit()

    def execute(self, sql, params=()):
        with self.lock:
            cur = self.db.execute(sql, params)
            self.db.commit()
            return cur

    def query(self, sql, params=()):
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    def insert(self, table, **row):
        cols = ",".join(row)
        cur = self.execute(f"insert into {table} ({cols}) values ({','.join('?' * len(row))})",
                           list(row.values()))
        return cur.lastrowid

    def update(self, table, row_id, **fields):
        sets = ",".join(f"{k}=?" for k in fields)
        self.execute(f"update {table} set {sets} where id=?", [*fields.values(), row_id])

    def delete(self, table, row_id):
        self.execute(f"delete from {table} where id=?", (row_id,))


class History:
    """Dictation history + the stats Wispr shows on Home and Insights."""

    def __init__(self, db: Database):
        self.db = db

    def add(self, **row):
        row.setdefault("ts", time.time())
        text = row.get("final_text") or ""
        row.setdefault("words", len(text.split()))
        return self.db.insert("history", **row)

    def set_edited(self, row_id, edited_text):
        self.db.update("history", row_id, edited_text=edited_text)

    def last_text(self):
        rows = self.db.query("select final_text from history where mode='dictation' and status='ok'"
                             " order by ts desc limit 1")
        return rows[0]["final_text"] if rows else None

    def recent(self, limit=200, offset=0, search=""):
        sql = ("select id, ts, mode, app, category, language, asr_text, final_text, edited_text, words,"
               " audio_ms, total_ms, status, source, audio is not null as has_audio from history")
        params = []
        if search:
            sql += " where final_text like ? or asr_text like ?"
            params += [f"%{search}%", f"%{search}%"]
        sql += " order by ts desc limit ? offset ?"
        return self.db.query(sql, params + [limit, offset])

    def get(self, row_id):
        rows = self.db.query("select * from history where id=?", (row_id,))
        return rows[0] if rows else None

    def delete(self, row_id):
        self.db.delete("history", row_id)

    def purge_older_than(self, seconds):
        self.db.execute("delete from history where ts < ?", (time.time() - seconds,))

    # ------------------------------------------------------------------ stats
    def stats(self):
        """Wispr's local stats: totalWords, averageWPM (last 100), day streaks, apps, fixes."""
        ok = "status='ok' and words > 0"
        total = self.db.query(f"select coalesce(sum(words),0) w, count(distinct lower(app)) apps,"
                              f" coalesce(sum(replacements),0) fixes from history where {ok}")[0]
        last = self.db.query(f"select words, coalesce(nullif(speech_ms,0), audio_ms) ms from history"
                             f" where {ok} and coalesce(nullif(speech_ms,0), audio_ms) > 0"
                             f" order by ts desc limit 100")
        minutes = sum(r["ms"] for r in last) / 60000
        wpm = round(sum(r["words"] for r in last) / minutes) if minutes else 0
        days = self.words_per_day()
        current, longest = _streaks(sorted(days))
        corrected = 0
        for r in self.db.query("select final_text, edited_text from history where edited_text is not null"
                               " and edited_text != final_text"):
            corrected += _changed_words(r["final_text"] or "", r["edited_text"] or "")
        week_ago = time.time() - 7 * 86400
        this_week = self.db.query(f"select coalesce(sum(words),0) w from history where {ok} and ts>=?",
                                  (week_ago,))[0]["w"]
        return {"total_words": total["w"], "wpm": wpm, "day_streak": current,
                "longest_streak": longest, "apps": total["apps"], "dictionary_fixes": total["fixes"],
                "words_corrected": corrected, "words_this_week": this_week}

    def words_per_day(self, since_days=400):
        rows = self.db.query(
            "select date(ts, 'unixepoch', 'localtime') d, sum(words) w from history"
            " where status='ok' and ts >= ? group by d", (time.time() - since_days * 86400,))
        return {dt.date.fromisoformat(r["d"]): r["w"] for r in rows}

    def usage_by_category(self):
        rows = self.db.query("select category, count(*) n from history where status='ok' and"
                             " mode='dictation' group by category")
        out = {}
        for r in rows:
            app_type = (r["category"] or "other/").split("/")[0]
            out[app_type] = out.get(app_type, 0) + r["n"]
        return out


def _changed_words(before, after):
    import difflib
    a, b = before.split(), after.split()
    changed = 0
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if op != "equal":
            changed += max(i2 - i1, j2 - j1)
    return changed


def _streaks(days):
    """(current streak ending today or yesterday, longest streak) in consecutive days."""
    if not days:
        return 0, 0
    longest = run = 1
    for a, b in zip(days, days[1:]):
        run = run + 1 if (b - a).days == 1 else 1
        longest = max(longest, run)
    today = dt.date.today()
    current = 0
    if days[-1] in (today, today - dt.timedelta(days=1)):
        current, d = 1, days[-1]
        idx = len(days) - 1
        while idx > 0 and (days[idx] - days[idx - 1]).days == 1:
            current += 1
            idx -= 1
    return current, longest


def migrate_legacy(db: Database):
    """Bring over history.sqlite / dictionary.json from the earlier FlowLite versions."""
    old_hist = DATA_DIR / "history.sqlite"
    if old_hist.exists() and not db.query("select 1 from history limit 1"):
        old = sqlite3.connect(old_hist)
        for ts, mode, app, title, category, asr, final, edited, audio_ms, total_ms, used_llm in old.execute(
                "select ts, mode, app, title, category, asr_text, final_text, edited_text, audio_ms,"
                " total_ms, used_llm from history"):
            db.insert("history", ts=ts, mode=mode, app=app, title=title, category=category,
                      asr_text=asr, final_text=final, edited_text=edited,
                      words=len((final or "").split()), audio_ms=audio_ms, total_ms=total_ms,
                      used_llm=used_llm)
        old.close()
        old_hist.rename(old_hist.with_suffix(".sqlite.migrated"))
    old_dict = DATA_DIR / "dictionary.json"
    if old_dict.exists():
        data = json.loads(old_dict.read_text(encoding="utf-8"))
        now = time.time()
        for w in data.get("vocabulary", []):
            db.insert("dictionary", phrase=w, source="manual", created=now, modified=now)
        for w in data.get("learned", []):
            db.insert("dictionary", phrase=w, source="learned", created=now, modified=now)
        for k, v in data.get("replacements", {}).items():
            db.insert("dictionary", phrase=k, replacement=v, source="manual", created=now, modified=now)
        for k, v in data.get("snippets", {}).items():
            db.insert("dictionary", phrase=k, replacement=v, is_snippet=1, source="manual",
                      created=now, modified=now)
        old_dict.rename(old_dict.with_suffix(".json.migrated"))
