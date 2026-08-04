"""
Text Cleaning & Normalisation
─────────────────────────────
Strips the furniture out of PDF-extracted regulation text — contents pages,
running headers, page numbers — and standardises characters so that two
documents typeset by different regulators compare on their words rather than
on their punctuation.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter

# A contents line: any text trailed by dot leaders and a page number.
# Regulators all typeset contents this way, and left in place these become
# hundreds of phantom clauses that swamp a comparison.
_CONTENTS_LINE = re.compile(r"^.{0,120}?[.․‧]{4,}\s*\d{1,4}\s*$")

# The same idea without leaders: a short heading ending in a bare page number.
_CONTENTS_BARE = re.compile(r"^[A-Z][^.!?]{3,70}\s{2,}\d{1,4}\s*$")

_PAGE_NUMBER = re.compile(r"^[-—]?\s*\d{1,4}\s*[-—]?$")
_PAGE_LABEL = re.compile(r"^[Pp]age\s+\d+(\s+of\s+\d+)?$", re.IGNORECASE)
_PAGE_OF = re.compile(r"^\d+\s+of\s+\d+$", re.IGNORECASE)

# A running header repeats on most pages. Anything shorter than this that
# recurs this often is furniture, not content.
_HEADER_MAX_CHARS = 90
_HEADER_MIN_REPEATS = 8

_REPLACEMENTS = {
    "‘": "'", "’": "'",       # curly single quotes
    "“": '"', "”": '"',       # curly double quotes
    "–": "-", "—": "-",       # en / em dash
    "…": "...",                     # ellipsis
    " ": " ",                       # non-breaking space
    "​": "", "‌": "", "‍": "", "﻿": "",  # zero-width
    "­": "",                        # soft hyphen
    "•": "- ", "●": "- ", "○": "- ",           # bullets
    "▪": "- ", "·": "- ",
    "×": "x",                       # multiplication sign in dimensions
}


def clean_text(raw_text: str) -> str:
    """
    Full cleaning pipeline for raw PDF text.

    Args:
        raw_text: Text as it came out of the extractor.

    Returns:
        Text ready for clause parsing.
    """
    text = unicodedata.normalize("NFC", unicodedata.normalize("NFKD", raw_text))
    text = _standardize_characters(text)

    # Normalise exotic whitespace to plain spaces, then drop control characters.
    text = re.sub(r"[^\S\n\t]", " ", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)

    lines = text.split("\n")
    lines = _drop_running_headers(lines)
    lines = [line for line in lines if not _is_furniture(line.strip())]

    return _collapse_whitespace("\n".join(lines)).strip()


def _standardize_characters(text: str) -> str:
    for old, new in _REPLACEMENTS.items():
        text = text.replace(old, new)
    return text


def _is_furniture(line: str) -> bool:
    """True for page numbers, contents entries, and other non-content lines."""
    if not line:
        return False
    if _PAGE_NUMBER.match(line) or _PAGE_LABEL.match(line) or _PAGE_OF.match(line):
        return True
    if _CONTENTS_LINE.match(line) or _CONTENTS_BARE.match(line):
        return True
    # Stray punctuation left behind by column splitting.
    if len(line) < 3 and not any(c.isalpha() for c in line):
        return True
    return False


def _drop_running_headers(lines: list[str]) -> list[str]:
    """
    Remove the header or footer printed on every page.

    Identified by repetition rather than by a per-publisher pattern list, which
    is what lets the pipeline take a PDF from a jurisdiction it has never seen.
    Lines that open a clause are never removed, however often they repeat.
    """
    counts = Counter(
        stripped for line in lines
        if 3 < len(stripped := line.strip()) <= _HEADER_MAX_CHARS
    )

    repeated = {
        line for line, count in counts.items()
        if count >= _HEADER_MIN_REPEATS and not line[0].isdigit()
    }

    if not repeated:
        return lines

    return [line for line in lines if line.strip() not in repeated]


def _collapse_whitespace(text: str) -> str:
    """Squeeze runs of spaces and blank lines, and trim every line."""
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return "\n".join(line.rstrip() for line in text.split("\n"))
