"""Learn dictionary words from your corrections after a paste (Wispr: auto-learn words).

Wispr's helper watches the field after pasting and reports pastedText/editedText.
The client trims the common prefix/suffix, aligns the remaining words with a weighted
Levenshtein (insert/delete = 1, substitute = 4 x normalized character distance) and
takes isolated substitutions as candidates (max 4), skipping stopwords, contractions
and words already in the dictionary.
"""

import re
import threading
import time

from . import context

STOPWORDS = set("""a an the and or but if then so to of in on at by for with from as is are was were be been
being it its this that these those i me my we our you your he him his she her they them their what which who
whom whose when where why how all any both each few more most other some such no nor not only own same than
too very can will just do does did done have has had having would should could ok okay yes yeah hi hey""".split())

OBSERVE_SECONDS = 30
POLL_SECONDS = 1.0


def _char_distance(a, b):
    a, b = a.lower(), b.lower()
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1] / max(len(a), len(b), 1)


def align(pasted, edited):
    """Word alignment. Returns a list of (label, pasted_word, edited_word).

    Labels: M match, C casing-only, S substitution, I inserted, D deleted.
    """
    a, b = pasted.split(), edited.split()
    n, m = len(a), len(b)
    cost = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        cost[i][0] = i
    for j in range(1, m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            wa, wb = _bare(a[i - 1]), _bare(b[j - 1])
            sub = 0.0 if wa.lower() == wb.lower() else 4 * _char_distance(wa, wb)
            cost[i][j] = min(cost[i - 1][j] + 1, cost[i][j - 1] + 1, cost[i - 1][j - 1] + sub)
    ops, i, j = [], n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0:
            wa, wb = _bare(a[i - 1]), _bare(b[j - 1])
            sub = 0.0 if wa.lower() == wb.lower() else 4 * _char_distance(wa, wb)
            if abs(cost[i][j] - (cost[i - 1][j - 1] + sub)) < 1e-9:
                label = "M" if wa == wb else ("C" if wa.lower() == wb.lower() else "S")
                ops.append((label, a[i - 1], b[j - 1]))
                i, j = i - 1, j - 1
                continue
        if i > 0 and abs(cost[i][j] - (cost[i - 1][j] + 1)) < 1e-9:
            ops.append(("D", a[i - 1], None))
            i -= 1
        else:
            ops.append(("I", None, b[j - 1]))
            j -= 1
    return ops[::-1]


def _bare(word):
    return word.strip(".,!?;:\"'()[]{}")


def candidates(pasted, edited, known=()):
    # Trim the common prefix/suffix (by characters) so only the edited region remains.
    p = 0
    while p < min(len(pasted), len(edited)) and pasted[p] == edited[p]:
        p += 1
    p = pasted.rfind(" ", 0, p) + 1  # back up to a word boundary
    s = 0
    while s < min(len(pasted), len(edited)) - p and pasted[-1 - s] == edited[-1 - s]:
        s += 1
    cut = len(pasted) - s  # move the cut forward to a word boundary
    while 0 < cut < len(pasted) and not pasted[cut - 1].isspace() and not pasted[cut].isspace():
        cut += 1
    s = len(pasted) - cut
    ops = align(pasted[p:len(pasted) - s] if s else pasted[p:],
                edited[p:len(edited) - s] if s else edited[p:])
    known_lower = {k.lower() for k in known}
    out = []
    for idx, (label, _, new) in enumerate(ops):
        if label != "S":
            continue
        left = ops[idx - 1][0] if idx > 0 else None
        right = ops[idx + 1][0] if idx + 1 < len(ops) else None
        if left == "S" or right == "S":
            continue
        word = _bare(new)
        if (not word or word.lower() in STOPWORDS or word.lower() in known_lower
                or "'" in word or "’" in word or word.isdigit() or len(word) < 2
                or re.search(r"[぀-ヿ一-鿿]", word)):
            continue
        if word not in out:
            out.append(word)
    out.sort(key=lambda w: not w[:1].isupper())  # prefer capitalized (names, brands)
    return out[:4]


class EditObserver:
    """Polls the focused field after a paste and reports the edited version of the paste."""

    def __init__(self, on_result):
        self.on_result = on_result  # callback(history_id, pasted, edited)
        self._generation = 0

    def watch(self, history_id, ctx, pasted):
        if ctx.element_key is None:
            return
        self._generation += 1
        gen = self._generation
        threading.Thread(target=self._run, args=(gen, history_id, ctx, pasted), daemon=True).start()

    def cancel(self):
        self._generation += 1  # a new dictation ends the previous observation

    def _run(self, gen, history_id, ctx, pasted):
        before, after = ctx.before_text, ctx.after_text
        latest = None
        deadline = time.monotonic() + OBSERVE_SECONDS
        while time.monotonic() < deadline and gen == self._generation:
            time.sleep(POLL_SECONDS)
            key, text = context.read_focused_field()
            if key != ctx.element_key or text is None:
                break  # focus moved away: observation ends
            if text.startswith(before) and text.endswith(after) and len(text) >= len(before) + len(after):
                latest = text[len(before):len(text) - len(after) if after else None]
        if latest is not None and latest.strip() != pasted.strip():
            self.on_result(history_id, pasted.strip(), latest.strip())
