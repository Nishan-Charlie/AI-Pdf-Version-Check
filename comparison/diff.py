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
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from html import escape
from typing import Optional

# Words, numbers with units ("600mm"), punctuation, and whitespace runs are
# each their own token. Splitting punctuation off means "750mm." vs "600mm."
# highlights the measurement, not the sentence.
_TOKEN = re.compile(r"\s+|[^\W_]+(?:['’][^\W_]+)*|[^\s\w]|_")

# Sentence ends and line breaks. Both alternatives are zero-width look-arounds
# on purpose: re.split discards whatever the pattern consumes, so matching the
# whitespace between sentences would silently drop it and the panes would no
# longer reproduce the clause they quote.
_SEGMENT_BOUNDARY = re.compile(r"(?<=[.;:!?])(?=\s)|(?<=\n)")

# Longest combined token count still diffed word by word in one pass. Above
# this the quadratic matcher is too slow to run inside a request, so the text
# is matched sentence by sentence first. Sized above the 95th percentile clause
# in the corpus, so ordinary clauses take the exact path.
WORD_DIFF_MAX_TOKENS = 1500

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

    # SequenceMatcher is quadratic in the length of its inputs. Regulation
    # clauses reach twelve thousand tokens, and a single pair that size was
    # measured taking eleven seconds — enough, over a few hundred such rows, to
    # outlast any request. Long pairs are therefore diffed in two passes; short
    # ones, which are the overwhelming majority, go straight through.
    if len(tokens_v1) + len(tokens_v2) <= WORD_DIFF_MAX_TOKENS:
        pieces = _diff_tokens(tokens_v1, tokens_v2)
    else:
        pieces = _diff_segments(text_v1, text_v2)

    return Redline(
        html_v1="".join(pieces.parts_v1),
        html_v2="".join(pieces.parts_v2),
        html_unified="".join(pieces.parts_unified),
        words_removed=pieces.removed,
        words_added=pieces.added,
        words_unchanged=pieces.unchanged,
    )


@dataclass
class _Pieces:
    """Rendered fragments and word counts, so the two passes compose."""

    parts_v1: list[str] = field(default_factory=list)
    parts_v2: list[str] = field(default_factory=list)
    parts_unified: list[str] = field(default_factory=list)
    removed: int = 0
    added: int = 0
    unchanged: int = 0

    def extend(self, other: "_Pieces") -> None:
        self.parts_v1.extend(other.parts_v1)
        self.parts_v2.extend(other.parts_v2)
        self.parts_unified.extend(other.parts_unified)
        self.removed += other.removed
        self.added += other.added
        self.unchanged += other.unchanged

    def mark(self, tokens_v1: list[str], tokens_v2: list[str]) -> None:
        """Record one side as deleted and the other as inserted, wholesale."""
        if tokens_v1:
            marked = _render(tokens_v1, DEL_OPEN, DEL_CLOSE)
            self.parts_v1.append(marked)
            self.parts_unified.append(marked)
            self.removed += _count_words(tokens_v1)
        if tokens_v2:
            marked = _render(tokens_v2, INS_OPEN, INS_CLOSE)
            self.parts_v2.append(marked)
            self.parts_unified.append(marked)
            self.added += _count_words(tokens_v2)


def _diff_tokens(tokens_v1: list[str], tokens_v2: list[str]) -> _Pieces:
    """Exact word-level diff. Quadratic, so only used on bounded input."""
    # autojunk drops tokens that appear in more than 1% of a long sequence,
    # which in regulation text means "the", "shall", "fire" — exactly the
    # words that anchor a correct alignment. It has to be off.
    matcher = SequenceMatcher(a=tokens_v1, b=tokens_v2, autojunk=False)
    pieces = _Pieces()

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        run_v1 = tokens_v1[i1:i2]
        run_v2 = tokens_v2[j1:j2]

        if op == "equal":
            plain = _render(run_v1)
            pieces.parts_v1.append(plain)
            pieces.parts_v2.append(plain)
            pieces.parts_unified.append(plain)
            pieces.unchanged += _count_words(run_v1)
            continue

        pieces.mark(run_v1 if op in ("delete", "replace") else [],
                    run_v2 if op in ("insert", "replace") else [])

    return pieces


def _diff_segments(text_v1: str, text_v2: str) -> _Pieces:
    """
    Two-pass diff for long clauses.

    First match whole sentences against each other — a few dozen units rather
    than thousands of tokens, so the quadratic cost collapses. Sentences that
    survive unchanged are emitted as they are; only the regions that actually
    differ are diffed word by word, and each of those is small.

    The result is what a reader wants anyway: an unchanged paragraph is not
    picked apart looking for coincidental word matches in a paragraph
    elsewhere, which is what the single-pass diff does on long text.
    """
    segments_v1 = _segments(text_v1)
    segments_v2 = _segments(text_v2)

    matcher = SequenceMatcher(a=segments_v1, b=segments_v2, autojunk=False)
    pieces = _Pieces()

    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        run_v1 = segments_v1[i1:i2]
        run_v2 = segments_v2[j1:j2]

        if op == "equal":
            plain = _render(run_v1)
            pieces.parts_v1.append(plain)
            pieces.parts_v2.append(plain)
            pieces.parts_unified.append(plain)
            # Count the words inside the segments, not the segments: each one
            # is a whole sentence, so counting them directly would report a
            # paragraph as a handful of words.
            pieces.unchanged += _count_words(tokenize("".join(run_v1)))
            continue

        if op == "delete":
            pieces.mark(tokenize("".join(run_v1)), [])
            continue
        if op == "insert":
            pieces.mark([], tokenize("".join(run_v2)))
            continue

        # A replaced region: worth a word-level diff if it is small enough,
        # otherwise marked whole. Rewritten wholesale reads the same either way.
        inner_v1 = tokenize("".join(run_v1))
        inner_v2 = tokenize("".join(run_v2))
        if len(inner_v1) + len(inner_v2) <= WORD_DIFF_MAX_TOKENS:
            pieces.extend(_diff_tokens(inner_v1, inner_v2))
        else:
            pieces.mark(inner_v1, inner_v2)

    return pieces


def _segments(text: str) -> list[str]:
    """
    Split into sentences, keeping every character so the text rebuilds exactly.

    Sentence ends and line breaks are the boundaries a regulation is actually
    edited at, which is what makes them the right unit for the coarse pass.
    """
    parts = _SEGMENT_BOUNDARY.split(text)
    return [p for p in parts if p]


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
