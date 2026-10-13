"""Personal dictionary and snippets, stored in flowlite.sqlite.

Mirrors Wispr's Dictionary table: plain words (vocabulary hints), replacements
("misspelling" -> "correct spelling"), snippets (trigger -> expansion), and words
auto-learned from your edits (shown with a sparkle).
"""

import re
import time


class Dictionary:
    def __init__(self, db):
        self.db = db

    # ------------------------------------------------------------------ CRUD
    def entries(self, snippets=False, search="", sort="newest"):
        order = {"newest": "created desc", "oldest": "created asc",
                 "alpha": "lower(phrase) asc", "starred": "starred desc, created desc"}[sort]
        sql = "select * from dictionary where is_snippet=?"
        params = [1 if snippets else 0]
        if search:
            sql += " and (phrase like ? or replacement like ?)"
            params += [f"%{search}%", f"%{search}%"]
        return self.db.query(f"{sql} order by {order}", params)

    def add(self, phrase, replacement=None, snippet=False, source="manual"):
        now = time.time()
        return self.db.insert("dictionary", phrase=phrase.strip(), replacement=(replacement or None),
                              is_snippet=int(snippet), source=source, created=now, modified=now)

    def update(self, entry_id, **fields):
        self.db.update("dictionary", entry_id, modified=time.time(), **fields)

    def remove(self, entry_id):
        self.db.delete("dictionary", entry_id)

    def star(self, entry_id, starred=True):
        self.db.update("dictionary", entry_id, starred=int(starred))

    # ------------------------------------------------------- dictation hooks
    def all_words(self, limit=150):
        rows = self.db.query("select phrase, replacement from dictionary where is_snippet=0"
                             " order by starred desc, used desc, created desc limit ?", (limit,))
        out, seen = [], set()
        for r in rows:
            w = r["replacement"] or r["phrase"]
            if w.lower() not in seen:
                seen.add(w.lower())
                out.append(w)
        return out

    def learn(self, word):
        exists = self.db.query("select 1 from dictionary where lower(phrase)=lower(?) or"
                               " lower(replacement)=lower(?)", (word, word))
        if exists:
            return False
        self.add(word, source="learned")
        return True

    def _replacements(self):
        return self.db.query("select id, phrase, replacement from dictionary where"
                             " replacement is not null and replacement != ''")

    def apply_count(self, text):
        """Apply replacements and in-text snippets; return (text, number of replacements)."""
        n = 0
        for r in self._replacements():
            pattern = r"(?<!\w)" + re.escape(r["phrase"]) + r"(?!\w)"
            text, k = re.subn(pattern, lambda _m, w=r["replacement"]: w, text, flags=re.IGNORECASE)
            if k:
                n += k
                self.db.execute("update dictionary set used=used+? where id=?", (k, r["id"]))
        return text, n

    def apply(self, text):
        return self.apply_count(text)[0]

    def snippet_for(self, text):
        """Whole-utterance snippet match ("my email address" -> the address)."""
        key = re.sub(r"[^\w\s]", "", text).strip().lower()
        for r in self.db.query("select id, phrase, replacement from dictionary where is_snippet=1"):
            if key == re.sub(r"[^\w\s]", "", r["phrase"]).strip().lower():
                self.db.execute("update dictionary set used=used+1 where id=?", (r["id"],))
                return r["replacement"]
        return None
