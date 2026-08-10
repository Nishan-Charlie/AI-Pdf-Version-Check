"""
Word-Level Redline
──────────────────
Turns a pair of clause texts into marked-up HTML that pinpoints the exact
words that changed, the way an amendment is marked up on paper: struck-through
red for what the new edition removed, underlined green for what it added.

The markup is generated here rather than in the browser so that the same
redline appears in the UI, in an export, and in any downstream report.

Everything that comes out of this module is HTML-escaped. Regulation text is
untrusted input — it arrives from an arbitrary uploaded PDF — so the only
angle brackets in the output are the ones this module writes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from html import escape
from typing import Optional

# Words, numbers with units ("600mm"), punctuation, and whitespace runs are
# each their own token. Splitting punctuation off means "750mm." vs "600mm."
# highlights the measurement, not the sentence.
_TOKEN = re.compile(r"\s+|[^\W_]+(?:['’][^\W_]+)*|[^\s\w]|_")

DEL_OPEN = '<del class="rl-del">'
DEL_CLOSE = "</del>"
INS_OPEN = '<ins class="rl-ins">'
INS_CLOSE = "</ins>"


@dataclass
class Redline:
    """A clause pair rendered as three views of the same change."""

    html_v1: str            # baseline, deletions marked
    html_v2: str            # revision, insertions marked
    html_unified: str       # one stream, deletions then insertions in place
    words_removed: int
    words_added: int
    words_unchanged: int

    @property
    def total_words(self) -> int:
        return self.words_unchanged + self.words_removed + self.words_added

    @property
    def word_change_ratio(self) -> float:
        """Share of words touched — a literal counterpart to the embedding score."""
        if self.total_words == 0:
            return 0.0
        return (self.words_removed + self.words_added) / self.total_words

    @property
    def has_changes(self) -> bool:
        return bool(self.words_removed or self.words_added)

    def as_dict(self, include_unified: bool = False) -> dict:
        """
        The wire form of a redline.

        `html_unified` is left out by default. It is a third rendering of text
        already present in `html_v1` and `html_v2`, and the dashboard shows the
        two panes rather than a merged stream — including it added a quarter to
        the size of every comparison response for a field nothing read.
        """
        payload = {
            "html_v1": self.html_v1,
            "html_v2": self.html_v2,
            "words_removed": self.words_removed,
            "words_added": self.words_added,
            "words_unchanged": self.words_unchanged,
            "word_change_ratio": round(self.word_change_ratio, 4),
        }
        if include_unified:
            payload["html_unified"] = self.html_unified
        return payload


def tokenize(text: str) -> list[str]:
    """Split text into diffable tokens, keeping whitespace so it can be rebuilt."""
    return _TOKEN.findall(text or "")


def _is_word(token: str) -> bool:
    return bool(token.strip())


def _count_words(tokens: list[str]) -> int:
    return sum(1 for token in tokens if _is_word(token))


def _render(tokens: list[str], open_tag: str = "", close_tag: str = "") -> str:
    """Escape a token run and, if marked, wrap it in a single tag."""
    if not tokens:
        return ""
    body = escape("".join(tokens), quote=False)
    if not open_tag:
        return body
    if not body.strip():
        # Never open a tag around pure whitespace: an empty red box between
        # two words reads as a change that isn't there.
        return body
    return f"{open_tag}{body}{close_tag}"


def redline(text_v1: Optional[str], text_v2: Optional[str]) -> Redline:
    """
    Compare two clause texts word by word.

    A missing side means the clause was added or removed outright, and the
    whole of the surviving text is marked accordingly.
    """
    if text_v1 is None and text_v2 is None:
        return Redline("", "", "", 0, 0, 0)

    if text_v1 is None:
        tokens = tokenize(text_v2 or "")
        marked = _render(tokens, INS_OPEN, INS_CLOSE)
        return Redline("", marked, marked, 0, _count_words(tokens), 0)

    if text_v2 is None:
        tokens = tokenize(text_v1)
        marked = _render(tokens, DEL_OPEN, DEL_CLOSE)
        return Redline(marked, "", marked, _count_words(tokens), 0, 0)

    tokens_v1 = tokenize(text_v1)
    tokens_v2 = tokenize(text_v2)

    # autojunk drops tokens that appear in more than 1% of a long sequence,
    # which in regulation text means "the", "shall", "fire" — exactly the
    # words that anchor a correct alignment. It has to be off.
    matcher = SequenceMatcher(a=tokens_v1, b=tokens_v2, autojunk=False)

    parts_v1: list[str] = []
    parts_v2: list[str] = []
    parts_unified: list[str] = []

    removed = added = unchanged = 0

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        run_v1 = tokens_v1[i1:i2]
        run_v2 = tokens_v2[j1:j2]

        if op == "equal":
            plain = _render(run_v1)
            parts_v1.append(plain)
            parts_v2.append(plain)
            parts_unified.append(plain)
            unchanged += _count_words(run_v1)
            continue

        if op in ("delete", "replace"):
            marked = _render(run_v1, DEL_OPEN, DEL_CLOSE)
            parts_v1.append(marked)
            parts_unified.append(marked)
            removed += _count_words(run_v1)

        if op in ("insert", "replace"):
            marked = _render(run_v2, INS_OPEN, INS_CLOSE)
            parts_v2.append(marked)
            parts_unified.append(marked)
            added += _count_words(run_v2)

    return Redline(
        html_v1="".join(parts_v1),
        html_v2="".join(parts_v2),
        html_unified="".join(parts_unified),
        words_removed=removed,
        words_added=added,
        words_unchanged=unchanged,
    )


def lexical_similarity(text_v1: str, text_v2: str) -> float:
    """
    Token-overlap similarity in [0, 1].

    Complements the embedding score: an encoder can rate two clauses alike
    when one says 600mm and the other 750mm, but this will not.
    """
    tokens_v1 = [t.lower() for t in tokenize(text_v1) if _is_word(t)]
    tokens_v2 = [t.lower() for t in tokenize(text_v2) if _is_word(t)]

    if not tokens_v1 or not tokens_v2:
        return 0.0

    set_v1, set_v2 = set(tokens_v1), set(tokens_v2)
    intersection = len(set_v1 & set_v2)
    union = len(set_v1 | set_v2)

    return intersection / union if union else 0.0
