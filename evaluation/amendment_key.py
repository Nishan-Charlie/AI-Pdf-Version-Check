"""
Documentary Reference Standard
──────────────────────────────
Every change MHCLG makes to Approved Document B is published in an amendment
booklet that names the paragraphs it touches:

    Paragraph 10.14, delete the second note.
    Replace Diagram 2.7 with the following.
    After paragraph 15.12, insert the following.

That register is an authoritative statement of which clauses changed between
two editions, written by the body that changed them. Parsed into clause
references it becomes a reference standard for evaluating change detection —
one that does not depend on anybody's opinion.

What it can and cannot settle
    It settles *localisation*: which clauses the regulator amended.
    It does not settle *severity*: whether a given edit is minor or
    significant is a judgement, and for that see `annotation.py`, which
    prepares a sample for a human to label.

A booklet covers both volumes of ADB, in separate sections, so each amendment
is tagged with the volume it belongs to and comparisons are scored against the
matching volume only.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterator, Optional

from config import CORPUS_TEXT_DIR

# ── Reference shapes ─────────────────────────────────────────────────
# The identifier itself, without its noun: "10.14", "3.1", "B4", "C1", and
# the bare letters that name a whole appendix or annex ("Appendix B").
#
# The letter is matched case-sensitively via a scoped flag, because the noun
# in front of it is matched case-insensitively: without this, "Diagram to the
# following" reads "to" as a reference named "t".
_REF_BODY = r"(?:(?-i:[A-Z])\d{0,3}|\d{1,3})(?:\.\d{1,3})*"

# The noun in front of a reference decides how the clause parser stored it:
# "Table 3.1" is kept whole, "paragraph 3.1" is stored as bare "3.1".
_NOUN_KEEPS_PREFIX = {"table", "diagram", "figure", "appendix", "section"}

_REFERENCE = re.compile(
    rf"\b(?P<noun>paragraphs?|tables?|diagrams?|figures?|appendix|appendices|"
    rf"sections?|clauses?|regulation)\s+(?P<body>{_REF_BODY})(?![A-Za-z])",
    re.IGNORECASE,
)

# Imperative amendment instructions, in the forms the booklets actually use.
# Requiring the verb in an imperative position keeps ordinary cross-references
# inside replacement text ("in accordance with paragraph 3.5") out of the key.
_INSTRUCTION_PATTERNS = [
    re.compile(r"^\s*(?P<op>replace|delete|insert|add|amend|substitute)\b", re.IGNORECASE),
    re.compile(r"^\s*(?:after|before)\s+.{0,80}?,\s*(?P<op>insert|add)\b", re.IGNORECASE),
    re.compile(rf"\b(?:paragraphs?|tables?|diagrams?)\s+{_REF_BODY}\s*,\s*"
               r"(?P<op>replace|delete|insert|add|amend|substitute)\b", re.IGNORECASE),
    re.compile(r"^\s*(?:in|at)\s+.{0,80}?,\s*(?P<op>replace|delete|insert|add|amend)\b",
               re.IGNORECASE),
]

_OPERATION_ALIASES = {
    "replace": "replace", "substitute": "replace", "amend": "amend",
    "delete": "delete", "remove": "delete",
    "insert": "insert", "add": "insert",
}

_VOLUME = re.compile(r"Volume\s*(?P<number>[12])\s*[–—-]\s*(?:Dwellings|Buildings)", re.IGNORECASE)
_LIST_HEADING = re.compile(r"List of amendments", re.IGNORECASE)

# Instruction sentences are short; replacement bodies are long. The cap keeps
# whole quoted paragraphs from being read as instructions.
_MAX_INSTRUCTION_CHARS = 320


@dataclass(frozen=True)
class Amendment:
    """One published instruction to change one clause."""

    booklet: str                 # corpus key, e.g. "adb-amd-2025"
    volume: Optional[int]        # 1 or 2; None when the booklet does not say
    reference: str               # normalised, e.g. "10.14", "Table 3.1"
    aliases: frozenset[str]      # other spellings the parser may have stored
    operation: str               # replace | delete | insert | amend
    instruction: str             # the sentence it came from

    def matches(self, clause_number: str) -> bool:
        """Exact match against any accepted spelling of this reference."""
        candidate = clause_number.strip().casefold()
        return candidate in {a.casefold() for a in self.aliases}

    def covers(self, clause_number: str) -> bool:
        """
        Whether this amendment reaches the given clause, directly or by
        containing it.

        The regulator amends at whatever granularity suits: a paragraph
        ("Paragraph 10.14, delete the second note"), or a whole division
        ("Replace the whole of Section 17 with the following"). A section-level
        instruction is satisfied by a change anywhere inside that section, so
        scoring it only against a clause literally numbered "Section 17" would
        record a miss for a change the system did surface — as paragraph 17.1,
        17.2, and so on.
        """
        if self.matches(clause_number):
            return True

        candidate = clause_number.strip()

        # "Section 17" contains 17.1, 17.2 …
        section = re.match(r"^Section\s+(\d{1,3})$", self.reference, re.IGNORECASE)
        if section and re.match(rf"^{section.group(1)}\.\d", candidate):
            return True

        # "Appendix B" contains B1, Table B2, Diagram B3 …
        appendix = re.match(r"^Appendix\s+([A-Z])$", self.reference, re.IGNORECASE)
        if appendix:
            letter = appendix.group(1).upper()
            if re.match(rf"^(?:Table\s+|Diagram\s+|Figure\s+)?{letter}\d", candidate,
                        re.IGNORECASE):
                return True

        return False


def _normalise(noun: str, body: str) -> tuple[str, frozenset[str]]:
    """
    Turn "paragraph 10.14" into the clause number the parser would have stored,
    plus the other spellings it might plausibly appear under.
    """
    noun = noun.rstrip("s").casefold()
    if noun == "appendices":
        noun = "appendix"

    if noun in _NOUN_KEEPS_PREFIX:
        primary = f"{noun.capitalize()} {body}"
        aliases = {primary, body}
    else:
        # Bare paragraph numbers. A functional requirement like "B1" is stored
        # both bare and as "Requirement B1" depending on where it appears.
        primary = body
        aliases = {body, f"Requirement {body}", f"Section {body}"}

    return primary, frozenset(aliases)


_PAGE_MARKER = re.compile(r"\bPages?\s+\d{1,4}(?:\s*(?:to|-|–)\s*\d{1,4})?\s*", re.IGNORECASE)


_RANGE_TAIL = re.compile(
    rf"^\s*(?P<connector>to|and|,)\s*(?P<body>{_REF_BODY})", re.IGNORECASE
)
_SPLIT_REF = re.compile(r"^(?P<prefix>[A-Z]*)(?P<number>\d+)$")


def _expand_range(body: str, sentence: str, position: int) -> list[str]:
    """
    Expand "paragraphs B1 to B5" into B1, B2, B3, B4, B5.

    The register writes runs of consecutive clauses as a range, and scoring
    only the first endpoint would understate what the regulator changed.
    Ranges are expanded only when both endpoints share a prefix and differ in
    a single trailing number, so "3.7 to 3.8" expands but "Section 2 to
    Appendix B" is left as its endpoints.
    """
    bodies = [body]

    tail = _RANGE_TAIL.match(sentence[position:])
    if tail is None:
        return bodies

    other = tail.group("body")
    connector = tail.group("connector").casefold()

    if connector != "to":
        # "X and Y" names two clauses rather than a run.
        return [body, other]

    start, end = _SPLIT_REF.match(body), _SPLIT_REF.match(other)
    if not (start and end) or start.group("prefix") != end.group("prefix"):
        return [body, other]

    first, last = int(start.group("number")), int(end.group("number"))
    if not 0 <= last - first <= 40:
        return [body, other]

    prefix = start.group("prefix")
    return [f"{prefix}{value}" for value in range(first, last + 1)]


def _reflow(region: str) -> list[str]:
    """
    Rebuild sentences from PDF line breaks.

    Instructions wrap mid-phrase ("Replace the whole of Appendix B: … and\\n
    structures with the following."), so lines are joined before sentences are
    split, or the verb and its reference land in different lines.

    Each instruction is also preceded in the register by its section heading
    and a page number, all on their own lines. Once joined these run into the
    instruction — "Sprinkler systems Page 27 Replace paragraph 2.46 …" — and
    hide the imperative verb behind a heading. Breaking after the page marker
    puts the instruction back at the start of its own sentence.
    """
    joined = re.sub(r"\s*\n\s*", " ", region)
    joined = re.sub(r"\s{2,}", " ", joined)
    joined = _PAGE_MARKER.sub("\n", joined)

    parts = re.split(r"(?<=[.:])\s+(?=[A-Z])|\n", joined)
    return [part.strip() for part in parts if part and part.strip()]


def _regions(text: str) -> Iterator[tuple[Optional[int], str]]:
    """
    Yield (volume, text) for each "List of amendments" section.

    The volume is taken from the nearest volume heading above the list, which
    is how the booklets separate their two halves.
    """
    headings = list(_LIST_HEADING.finditer(text))
    if not headings:
        yield None, text
        return

    for index, heading in enumerate(headings):
        start = heading.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)

        preceding = [m for m in _VOLUME.finditer(text, 0, heading.start())]
        volume = int(preceding[-1].group("number")) if preceding else None

        yield volume, text[start:end]


def parse_booklet(text: str, booklet: str) -> list[Amendment]:
    """Extract every amendment instruction from one booklet's text."""
    amendments: list[Amendment] = []
    seen: set[tuple[Optional[int], str, str]] = set()

    for volume, region in _regions(text):
        for sentence in _reflow(region):
            if len(sentence) > _MAX_INSTRUCTION_CHARS:
                continue

            operation = _operation_of(sentence)
            if operation is None:
                continue

            for match in _REFERENCE.finditer(sentence):
                noun = match.group("noun")
                bodies = _expand_range(match.group("body"), sentence, match.end())

                for body in bodies:
                    primary, aliases = _normalise(noun, body)

                    fingerprint = (volume, primary, operation)
                    if fingerprint in seen:
                        continue
                    seen.add(fingerprint)

                    amendments.append(Amendment(
                        booklet=booklet,
                        volume=volume,
                        reference=primary,
                        aliases=aliases,
                        operation=operation,
                        instruction=sentence,
                    ))

    return amendments


def _operation_of(sentence: str) -> Optional[str]:
    for pattern in _INSTRUCTION_PATTERNS:
        match = pattern.search(sentence)
        if match:
            return _OPERATION_ALIASES.get(match.group("op").casefold())
    return None


def load_booklet(booklet_key: str) -> list[Amendment]:
    """Parse a booklet from the extracted text corpus."""
    path = os.path.join(CORPUS_TEXT_DIR, f"{booklet_key}.txt")
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"No extracted text for '{booklet_key}'. "
            "Run `python -m corpus.fetch --extract` first."
        )
    with open(path, encoding="utf-8") as handle:
        return parse_booklet(handle.read(), booklet_key)


def changed_references(
    booklet_keys: list[str],
    volume: Optional[int] = None,
) -> tuple[set[str], list[Amendment]]:
    """
    The set of clause spellings the regulator says changed.

    Args:
        booklet_keys: Amendment booklets covering the interval under test.
        volume: Restrict to one ADB volume. Amendments the booklet did not
            attribute to a volume are always included, since they cannot be
            ruled out.

    Returns:
        (every accepted spelling of every changed clause, the amendments)
    """
    amendments: list[Amendment] = []
    for key in booklet_keys:
        amendments.extend(load_booklet(key))

    if volume is not None:
        amendments = [a for a in amendments if a.volume in (volume, None)]

    spellings: set[str] = set()
    for amendment in amendments:
        spellings.update(amendment.aliases)

    return spellings, amendments
