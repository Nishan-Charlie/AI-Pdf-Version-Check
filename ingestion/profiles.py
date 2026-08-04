"""
Jurisdiction Parsing Profiles
─────────────────────────────
Every regulator numbers its clauses differently. A profile holds the grammar
for one publishing tradition: which line shapes open a new clause, how the
identifier is normalised, and which words identify the document when the user
does not tell us where it came from.

Adding a country means adding a profile here and a jurisdiction in config.py.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional, Pattern

# ── Shared line shapes ───────────────────────────────────────────────
# Dotted decimals ("2.14", "1.3.2.1") are the backbone of every regulation in
# the corpus; the profiles differ in what they add around them.
_DOTTED = r"(\d{1,2}(?:\.\d{1,3}){1,4})"

# Identifier alone on its own line — some PDFs break the number off the text.
_DOTTED_ALONE = re.compile(rf"^{_DOTTED}\s*$")

# List markers. These are clause *contents*, not clause starts, unless a
# document turns out to have no numeric structure at all.
_LIST_MARKER = re.compile(r"^(\(?[a-z]\)|\(?[ivx]{1,4}\)|\d{1,2}\))\s+\S")


@dataclass(frozen=True)
class ClauseRule:
    """One line shape that opens a clause, and how to read its identifier."""

    name: str
    pattern: Pattern[str]
    level: int = 1                      # structural depth hint
    is_heading: bool = False            # opens a section, not a paragraph
    format_id: Optional[Callable[[re.Match], str]] = None

    def identifier(self, match: re.Match) -> str:
        if self.format_id:
            return self.format_id(match)
        for group in match.groups():
            if group:
                return group.strip().rstrip(".")
        return match.group(0).strip()


@dataclass(frozen=True)
class ParserProfile:
    """The clause grammar for one publishing tradition."""

    name: str
    label: str
    rules: list[ClauseRule]
    signatures: list[str] = field(default_factory=list)
    noise: list[Pattern[str]] = field(default_factory=list)

    def match_line(self, line: str) -> Optional[tuple[ClauseRule, re.Match]]:
        """First rule that opens a clause on this line, if any."""
        for rule in self.rules:
            match = rule.pattern.match(line)
            if match:
                return rule, match
        return None

    def is_noise(self, line: str) -> bool:
        """Running headers and footers specific to this publisher."""
        return any(pattern.search(line) for pattern in self.noise)


def _depth(identifier: str) -> int:
    """Structural depth read off a dotted identifier."""
    return identifier.count(".") + 1


# ── Rules shared by every profile ────────────────────────────────────

def _numeric_rule() -> ClauseRule:
    return ClauseRule(
        name="paragraph",
        pattern=re.compile(rf"^{_DOTTED}\s+(?=[A-Z(\"'\d])"),
        level=2,
    )


def _numeric_alone_rule() -> ClauseRule:
    return ClauseRule(name="paragraph-split", pattern=_DOTTED_ALONE, level=2)


def _table_rules(prefixes: tuple[str, ...] = ("Table", "Diagram", "Figure")) -> list[ClauseRule]:
    rules = []
    for prefix in prefixes:
        rules.append(ClauseRule(
            name=prefix.lower(),
            pattern=re.compile(rf"^{prefix}\s+([\dA-Z]+(?:\.\d+)*)\b", re.IGNORECASE),
            level=3,
            format_id=lambda m, p=prefix: f"{p} {m.group(1)}",
        ))
    return rules


# ── England & Wales — Approved Document B ────────────────────────────
APPROVED_DOCUMENT = ParserProfile(
    name="approved_document",
    label="Approved Document (England & Wales)",
    rules=[
        ClauseRule(
            name="requirement",
            pattern=re.compile(r"^Requirement\s+(B[1-5])\b"),
            level=1,
            is_heading=True,
            format_id=lambda m: f"Requirement {m.group(1)}",
        ),
        ClauseRule(
            name="section",
            pattern=re.compile(r"^Section\s+(\d{1,2})\b[:.]?\s*"),
            level=1,
            is_heading=True,
            format_id=lambda m: f"Section {m.group(1)}",
        ),
        ClauseRule(
            name="appendix",
            pattern=re.compile(r"^Appendix\s+([A-Z])\b[:.]?\s*"),
            level=1,
            is_heading=True,
            format_id=lambda m: f"Appendix {m.group(1)}",
        ),
        ClauseRule(
            name="functional-requirement",
            pattern=re.compile(r"^(B[1-5])\s+(?=[A-Z])"),
            level=1,
            is_heading=True,
        ),
        _numeric_rule(),
        _numeric_alone_rule(),
        *_table_rules(),
    ],
    signatures=[
        "approved document b",
        "the building regulations 2010",
        "for use in england",
        "requirement b1",
        "mhclg",
    ],
    noise=[
        re.compile(r"^Approved Document B,? Volume \d", re.IGNORECASE),
        re.compile(r"^Fire safety:? Volume", re.IGNORECASE),
    ],
)


# ── Scotland — Technical Handbooks ───────────────────────────────────
TECHNICAL_HANDBOOK = ParserProfile(
    name="technical_handbook",
    label="Technical Handbook (Scotland)",
    rules=[
        ClauseRule(
            name="standard",
            pattern=re.compile(r"^Standard\s+(\d\.\d{1,2})\b"),
            level=1,
            is_heading=True,
            format_id=lambda m: f"Standard {m.group(1)}",
        ),
        ClauseRule(
            name="annex",
            pattern=re.compile(r"^Annex\s+(\d\.[A-Z])\b"),
            level=1,
            is_heading=True,
            format_id=lambda m: f"Annex {m.group(1)}",
        ),
        ClauseRule(
            name="section",
            pattern=re.compile(
                r"^(\d)\s+(?:Fire|Structure|Environment|Safety|Noise|Energy|"
                r"General|Sustainability)\b"
            ),
            level=1,
            is_heading=True,
            format_id=lambda m: f"Section {m.group(1)}",
        ),
        _numeric_rule(),
        _numeric_alone_rule(),
        *_table_rules(),
    ],
    signatures=[
        "technical handbook",
        "scottish ministers",
        "building (scotland) regulations",
        "mandatory standard",
        "building standards division",
    ],
    noise=[
        re.compile(r"^(?:Domestic|Non-domestic)\s+Technical Handbook", re.IGNORECASE),
        re.compile(r"^Scottish Government", re.IGNORECASE),
    ],
)


# ── Northern Ireland — Technical Booklet E ───────────────────────────
TECHNICAL_BOOKLET = ParserProfile(
    name="technical_booklet",
    label="Technical Booklet (Northern Ireland)",
    rules=[
        ClauseRule(
            name="part",
            pattern=re.compile(r"^Part\s+([A-Z])\b[:.]?\s*"),
            level=1,
            is_heading=True,
            format_id=lambda m: f"Part {m.group(1)}",
        ),
        ClauseRule(
            name="regulation",
            pattern=re.compile(r"^(E\d{1,2})\s+(?=[A-Z])"),
            level=1,
            is_heading=True,
        ),
        ClauseRule(
            name="section",
            pattern=re.compile(r"^Section\s+(\d{1,2})\b[:.]?\s*"),
            level=1,
            is_heading=True,
            format_id=lambda m: f"Section {m.group(1)}",
        ),
        _numeric_rule(),
        _numeric_alone_rule(),
        *_table_rules(),
    ],
    signatures=[
        "technical booklet",
        "building regulations (northern ireland)",
        "department of finance",
        "department of finance and personnel",
    ],
    noise=[
        re.compile(r"^Technical Booklet [A-Z]\b", re.IGNORECASE),
    ],
)


# ── Republic of Ireland — Technical Guidance Document B ──────────────
TECHNICAL_GUIDANCE = ParserProfile(
    name="technical_guidance",
    label="Technical Guidance Document (Ireland)",
    rules=[
        ClauseRule(
            name="requirement",
            pattern=re.compile(r"^(B[1-5])\s+(?=[A-Z])"),
            level=1,
            is_heading=True,
        ),
        ClauseRule(
            name="appendix",
            pattern=re.compile(r"^Appendix\s+([A-Z])\b[:.]?\s*"),
            level=1,
            is_heading=True,
            format_id=lambda m: f"Appendix {m.group(1)}",
        ),
        ClauseRule(
            name="paragraph-labelled",
            pattern=re.compile(rf"^Paragraph\s+{_DOTTED}\b"),
            level=2,
        ),
        _numeric_rule(),
        _numeric_alone_rule(),
        *_table_rules(),
    ],
    signatures=[
        "technical guidance document",
        "building regulations 2006",
        "second schedule",
        "department of housing, local government and heritage",
        "an roinn",
    ],
    noise=[
        re.compile(r"^Technical Guidance Document B", re.IGNORECASE),
    ],
)


# ── BSI — BS 9999 / BS 9991 / BS 7974 ────────────────────────────────
BRITISH_STANDARD = ParserProfile(
    name="british_standard",
    label="British Standard (BSI)",
    rules=[
        ClauseRule(
            name="annex",
            pattern=re.compile(r"^Annex\s+([A-Z])\b"),
            level=1,
            is_heading=True,
            format_id=lambda m: f"Annex {m.group(1)}",
        ),
        ClauseRule(
            name="annex-clause",
            pattern=re.compile(r"^([A-Z]\.\d{1,2}(?:\.\d{1,2})*)\s+(?=\S)"),
            level=2,
        ),
        ClauseRule(
            name="front-matter",
            pattern=re.compile(r"^(Foreword|Introduction|Scope|Bibliography)\s*$"),
            level=1,
            is_heading=True,
        ),
        ClauseRule(
            name="clause-labelled",
            pattern=re.compile(r"^Clause\s+(\d{1,2}(?:\.\d{1,3})*)\b"),
            level=2,
        ),
        ClauseRule(
            name="clause",
            pattern=re.compile(r"^(\d{1,2}(?:\.\d{1,3})*)\s+(?=[A-Z])"),
            level=2,
        ),
        *_table_rules(),
    ],
    signatures=[
        "british standard",
        "bs 9999",
        "bs 9991",
        "bs 7974",
        "bsi standards limited",
        "(normative)",
    ],
    noise=[
        re.compile(r"^BS \d{4}:\d{4}", re.IGNORECASE),
        re.compile(r"^©\s*(?:The )?BSI", re.IGNORECASE),
    ],
)


# ── Fallback for anything else ───────────────────────────────────────
GENERIC = ParserProfile(
    name="generic",
    label="Generic numbered document",
    rules=[
        ClauseRule(
            name="labelled",
            pattern=re.compile(r"^(?:Section|Clause|Part|Article)\s+(\d{1,3}(?:\.\d{1,3})*)\b",
                               re.IGNORECASE),
            level=1,
            is_heading=True,
        ),
        _numeric_rule(),
        ClauseRule(
            name="integer",
            pattern=re.compile(r"^(\d{1,3})\.\s+(?=[A-Z])"),
            level=1,
        ),
        _numeric_alone_rule(),
        *_table_rules(),
    ],
    signatures=[],
)


PROFILES: dict[str, ParserProfile] = {
    p.name: p
    for p in (
        APPROVED_DOCUMENT,
        TECHNICAL_HANDBOOK,
        TECHNICAL_BOOKLET,
        TECHNICAL_GUIDANCE,
        BRITISH_STANDARD,
        GENERIC,
    )
}


def get_profile(name: str | None) -> ParserProfile:
    """Look up a profile by name, falling back to the generic grammar."""
    return PROFILES.get(name or "", GENERIC)


def detect_profile(text: str, sample_chars: int = 40_000) -> tuple[ParserProfile, float]:
    """
    Work out which publishing tradition a document belongs to.

    Scores each profile on how often its signature phrases appear in the
    opening pages, then on how many lines its clause rules can read. Returns
    the winner and a 0–1 confidence.
    """
    head = text[:sample_chars]
    head_lower = head.lower()
    lines = [line.strip() for line in head.split("\n") if line.strip()]

    scores: dict[str, float] = {}
    for name, profile in PROFILES.items():
        if name == "generic":
            continue

        signature_hits = sum(head_lower.count(sig) for sig in profile.signatures)
        # Signature phrases are the strong evidence — a title page names its
        # own instrument. Structural hits only break ties between traditions
        # that share the dotted-decimal backbone.
        structural_hits = sum(1 for line in lines if profile.match_line(line))

        scores[name] = signature_hits * 10 + structural_hits * 0.5

    if not scores or max(scores.values()) == 0:
        return GENERIC, 0.0

    best_name = max(scores, key=scores.get)
    total = sum(scores.values()) or 1.0
    confidence = scores[best_name] / total

    return PROFILES[best_name], round(confidence, 3)


def looks_like_heading(line: str) -> bool:
    """
    A short line with no terminal punctuation that introduces what follows.

    Used to attach a section name to every clause so cross-country matching
    has topic context ("Means of escape") on top of clause text.
    """
    stripped = line.strip()
    if not (3 <= len(stripped) <= 80):
        return False
    if stripped[-1] in ".,;:":
        return False
    if _LIST_MARKER.match(stripped):
        return False
    words = stripped.split()
    if len(words) > 10:
        return False
    return stripped[0].isupper() or stripped.isupper()


def is_list_marker(line: str) -> bool:
    """True for "(a)", "iii)", "2)" style list items."""
    return bool(_LIST_MARKER.match(line.strip()))
