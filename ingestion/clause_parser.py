"""
Clause Parser Module
────────────────────
Splits cleaned Fire Safety document text into individual numbered clauses.
Handles common numbering schemes: 1.2.3, Section X, (a), a), 1), etc.
"""

import re
from typing import Optional


# Master regex that matches common clause/section numbering at the start of a line.
# Groups:
#   1 – hierarchical number like 1, 1.2, 1.2.3
#   2 – "Section/Clause/Part X.Y" style
#   3 – lettered items like a), (a)
#   4 – numbered items like 1), 2)
_CLAUSE_START_RE = re.compile(
    r"^(?:"
    r"(\d+(?:\.\d+)+)"                           # 1.2 or 1.2.3
    r"|(?:[Ss]ection|[Cc]lause|[Pp]art)\s+(\d+(?:\.\d+)*)"  # Section 1.2
    r"|(\(?[a-z]\))"                              # a) or (a)
    r"|(\d+\))"                                   # 1) 2)
    r")\s+",
    re.MULTILINE,
)


def parse_clauses(cleaned_text: str) -> list[dict]:
    """
    Parse cleaned document text into a list of clause dictionaries.

    Each clause dict contains:
        - clause_number (str): e.g., "1.2.3", "Section 4", "a)"
        - title (str | None):  First line if it looks like a title (short, no period)
        - content (str):       The full text body of the clause

    If no numbered clauses are detected, the entire text is returned
    as a single clause with clause_number "1".

    Args:
        cleaned_text: Pre-cleaned document text.

    Returns:
        List of clause dicts sorted by appearance order.
    """
    if not cleaned_text or not cleaned_text.strip():
        return []

    # Find all clause boundary positions
    matches = list(_CLAUSE_START_RE.finditer(cleaned_text))

    # If no structured clauses found, return entire text as one clause
    if not matches:
        return [_make_clause("1", None, cleaned_text.strip())]

    clauses: list[dict] = []

    for i, match in enumerate(matches):
        # Determine the clause number from whichever group matched
        clause_number = _extract_clause_number(match)

        # Content runs from end of this match to start of next match (or end of text)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(cleaned_text)
        content = cleaned_text[start:end].strip()

        # Try to extract a title from the first line
        title, body = _extract_title(content)

        clauses.append(_make_clause(clause_number, title, body))

    # If there's text BEFORE the first clause marker, prepend it as "Preamble"
    preamble_text = cleaned_text[: matches[0].start()].strip()
    if preamble_text and len(preamble_text) > 20:
        clauses.insert(0, _make_clause("0", "Preamble", preamble_text))

    return clauses


def _extract_clause_number(match: re.Match) -> str:
    """Extract the clause number string from the regex match groups."""
    if match.group(1):
        return match.group(1)
    elif match.group(2):
        return match.group(2)
    elif match.group(3):
        return match.group(3).strip("()")
    elif match.group(4):
        return match.group(4).rstrip(")")
    return "?"


def _extract_title(content: str) -> tuple[Optional[str], str]:
    """
    If the first line is short and looks like a heading (no trailing period,
    relatively short), treat it as the clause title.
    """
    if not content:
        return None, ""

    lines = content.split("\n", 1)
    first_line = lines[0].strip()

    # Heuristic: title if < 100 chars, doesn't end with period, and there's more content
    is_title = (
        len(lines) > 1
        and len(first_line) < 100
        and not first_line.endswith(".")
        and len(first_line.split()) <= 12
    )

    if is_title:
        body = lines[1].strip() if len(lines) > 1 else ""
        return first_line, body
    else:
        return None, content


def _make_clause(clause_number: str, title: Optional[str], content: str) -> dict:
    """Build a standardized clause dictionary."""
    return {
        "clause_number": clause_number,
        "title": title,
        "content": content,
    }
