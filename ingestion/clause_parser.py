"""
Clause Parser
─────────────
Splits cleaned regulation text into individual clauses using the numbering
grammar of the jurisdiction it came from (see `profiles.py`).

Each clause carries the context a cross-country comparison needs: its own
identifier, the section it sits under, its structural depth, and its position
in the document.
"""

from __future__ import annotations

import re
from typing import Optional

from config import MAX_CLAUSES_PER_VERSION, MIN_CLAUSE_CHARS
from ingestion.profiles import (
    ParserProfile,
    detect_profile,
    get_profile,
    is_list_marker,
    looks_like_heading,
)

_SPACES = re.compile(r"[^\S\n]+")

# Longest trailing text a clause marker may carry and still count as a heading.
MAX_HEADING_CHARS = 90


def parse_clauses(
    cleaned_text: str,
    profile: str | ParserProfile | None = None,
) -> list[dict]:
    """
    Parse cleaned document text into clause records.

    Each record contains:
        clause_number (str) — "2.14", "Requirement B3", "Annex A"
        title         (str | None)
        content       (str)
        section       (str | None) — nearest enclosing heading
        level         (int)        — 1 for sections, deeper for paragraphs
        ordinal       (int)        — position in the document, from 0

    Args:
        cleaned_text: Text that has already been through `clean_text`.
        profile: A ParserProfile, a profile name, or None to auto-detect.

    Returns:
        Clause records in document order.
    """
    if not cleaned_text or not cleaned_text.strip():
        return []

    if isinstance(profile, ParserProfile):
        active = profile
    elif profile:
        active = get_profile(profile)
    else:
        active, _ = detect_profile(cleaned_text)

    clauses = _split(cleaned_text, active)

    if not clauses:
        # Nothing numbered was found. Fall back to list markers, then to
        # treating the whole document as one clause.
        clauses = _split(cleaned_text, active, allow_list_markers=True)
    if not clauses:
        clauses = [_record("1", None, cleaned_text.strip(), None, 1)]

    clauses = _merge_fragments(clauses)
    clauses = _drop_navigational(clauses)
    clauses = clauses[:MAX_CLAUSES_PER_VERSION]

    for index, clause in enumerate(clauses):
        clause["ordinal"] = index

    return clauses


# ── Splitting ────────────────────────────────────────────────────────

def _split(
    text: str,
    profile: ParserProfile,
    allow_list_markers: bool = False,
) -> list[dict]:
    """Walk the document line by line, opening a clause at each marker."""
    clauses: list[dict] = []

    current_id: Optional[str] = None
    current_level = 1
    current_lines: list[str] = []
    current_section: Optional[str] = None
    preamble_lines: list[str] = []

    def close_current() -> None:
        if current_id is None:
            return
        content = _join(current_lines)
        title, body = _extract_title(content)
        clauses.append(_record(current_id, title, body, current_section, current_level))

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line or profile.is_noise(line):
            continue

        matched = profile.match_line(line)

        if matched is None and allow_list_markers and is_list_marker(line):
            # Fallback pass only: a document with no numbering of its own is
            # split on its list markers rather than left as one huge clause.
            marker = line.split()[0]
            close_current()
            current_id = marker.strip("().")
            current_level = 3
            current_lines = [line[len(marker):].strip()]
            continue

        if matched is None:
            if current_id is None:
                preamble_lines.append(line)
            else:
                current_lines.append(line)
            continue

        rule, match = matched
        close_current()

        remainder = line[match.end():].strip()

        # A heading is a short line. "Standard 3.1" opening a paragraph of
        # prose is a cross-reference inside a clause, not a new section, and
        # promoting it would relabel everything beneath it.
        opens_section = rule.is_heading and len(remainder) <= MAX_HEADING_CHARS

        current_id = rule.identifier(match)
        current_level = rule.level if opens_section or not rule.is_heading else 2
        current_lines = [remainder] if remainder else []

        if opens_section:
            # A section heading renames the context every clause below it
            # inherits. The heading text is the rest of the line.
            current_section = f"{current_id} {remainder}".strip() if remainder else current_id

    close_current()

    if not clauses:
        return []

    preamble = _join(preamble_lines)
    if len(preamble) >= MIN_CLAUSE_CHARS:
        clauses.insert(0, _record("0", "Preamble", preamble, None, 1))

    return clauses


def _join(lines: list[str]) -> str:
    """
    Reflow a clause's lines into readable prose.

    PDF extraction breaks sentences across lines arbitrarily, so lines are
    rejoined with spaces — except list items, which keep their own line so
    "(a) ... (b) ..." stays legible in the side-by-side view.
    """
    if not lines:
        return ""

    parts: list[str] = []
    for line in lines:
        if parts and is_list_marker(line):
            parts.append("\n" + line)
        else:
            parts.append(line)

    text = " ".join(parts)
    text = _SPACES.sub(" ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)

    # A heading split across lines ("Requirement B1" / ": Means of escape")
    # leaves its punctuation stranded at the front of the body.
    return text.strip().lstrip(":-–— ").strip()


def _extract_title(content: str) -> tuple[Optional[str], str]:
    """Promote a leading heading-like fragment to the clause title."""
    if not content:
        return None, ""

    head, _, tail = content.partition("\n")
    if tail and looks_like_heading(head):
        return head.strip(), tail.strip()

    # Titles also arrive inline: "Escape routes The building shall..."
    sentence_end = content.find(". ")
    if 0 < sentence_end < 60:
        return None, content

    return None, content


def _record(
    clause_number: str,
    title: Optional[str],
    content: str,
    section: Optional[str],
    level: int,
) -> dict:
    return {
        "clause_number": clause_number,
        "title": title,
        "content": content,
        "section": section,
        "level": level,
        "ordinal": 0,
    }


# ── Post-processing ──────────────────────────────────────────────────

def _merge_fragments(clauses: list[dict]) -> list[dict]:
    """
    Fold stubs back into the clause above them.

    Cross-references and stray table cells parse as one-line clauses. Kept
    separate they flood the comparison with noise pairs, so anything under
    `MIN_CLAUSE_CHARS` is appended to its predecessor instead — unless it is a
    section heading, which carries structure even when it is short.
    """
    merged: list[dict] = []

    for clause in clauses:
        is_substantial = len(clause["content"]) >= MIN_CLAUSE_CHARS
        is_structural = clause["level"] <= 1

        if merged and not is_substantial and not is_structural:
            previous = merged[-1]
            fragment = f"{clause['clause_number']} {clause['content']}".strip()
            previous["content"] = f"{previous['content']}\n{fragment}".strip()
            continue

        merged.append(clause)

    return [c for c in merged if c["content"].strip() or c["level"] <= 1]


# A clause body with no sentence-ending punctuation anywhere.
_NO_SENTENCE = re.compile(r"[.!?](?:\s|$)")

# Longest run of words a heading-only body may have and still be navigation.
_MAX_NAVIGATION_WORDS = 40


def _drop_navigational(clauses: list[dict]) -> list[dict]:
    """
    Remove contents listings that parsed as clauses.

    Regulations print a contents page, and several reprint a summary of
    headings at the start of each section. Where those pages have no dot
    leaders the cleaner cannot recognise them, so they arrive here as
    section-level clauses whose body is a run of headings rather than prose —
    "Appendix D / Methods of measurement Occupant number Travel distance".

    Left in, they pair against their own counterpart in the other edition and
    report large differences whenever the contents were re-flowed, which
    inflates the change count with entries that carry no requirement.

    The test is deliberately narrow: only section-level clauses, only when the
    body contains no sentence at all, and only when it is short. A clause that
    states a requirement ends its sentences with a full stop.
    """
    kept: list[dict] = []

    for clause in clauses:
        body = clause["content"].strip()
        is_heading = clause["level"] <= 1
        has_sentence = bool(_NO_SENTENCE.search(body))
        short = len(body.split()) <= _MAX_NAVIGATION_WORDS

        if is_heading and not has_sentence and short:
            continue

        kept.append(clause)

    return kept
