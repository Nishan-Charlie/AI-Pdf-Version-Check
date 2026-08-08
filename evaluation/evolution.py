"""
Patterns in Regulation Evolution
────────────────────────────────
How Approved Document B changed across its 2019, 2022, and 2025 editions, and
what the amendment registers say about where regulatory attention goes.

Two sources, deliberately:

    The documents themselves, compared clause by clause. This shows how much
    text moved and where.

    The amendment registers, which state what the regulator intended to change.
    This shows which parts of the guidance are revisited, independently of how
    much text a revision happened to touch.

Where the two disagree the disagreement is itself the finding — a consolidation
that announces amendments it does not contain, for instance.
"""

from __future__ import annotations

import re
from collections import Counter

from comparison.engine import SemanticComparator
from comparison.report import ChangeType
from config import ALIGNMENT_IDENTIFIER
from database.operations import get_clauses, list_all_versions
from evaluation.amendment_key import load_booklet
from evaluation.experiments import _ref, find_version

# The ADB volume 1 series, oldest first.
ADB_SERIES = [
    ("Volume 1: Dwellings", "2019 edition"),
    ("Volume 1: Dwellings", "2022 amendments"),
    ("Volume 1: Dwellings", "2025 amendments"),
]

REGISTERS = [
    ("May 2020", "adb-amd-2020"),
    ("June 2022", "adb-amd-2022"),
    ("March 2024", "adb-amd-2024"),
    ("2025", "adb-amd-2025"),
    ("2026", "adb-amd-2026"),
    ("2029", "adb-amd-2029"),
]

_SECTION_OF = re.compile(r"^(\d{1,2})\.")


def _section_of(clause_number: str) -> str:
    """Which section a clause belongs to, from its number."""
    match = _SECTION_OF.match(clause_number)
    if match:
        return f"Section {match.group(1)}"
    if clause_number.startswith(("Requirement", "B")):
        return "Requirements"
    for prefix in ("Appendix", "Table", "Diagram", "Section"):
        if clause_number.startswith(prefix):
            return prefix if prefix != "Section" else clause_number
    return "Other"


def run_evolution(comparator: SemanticComparator) -> dict:
    """Measure how the instrument grew and where it changed."""
    return {
        "study": "Patterns in regulation evolution",
        "series": _series_shape(),
        "transitions": _transitions(comparator),
        "register_attention": _register_attention(),
        "jurisdiction_sizes": _jurisdiction_sizes(),
    }


def _series_shape() -> list[dict]:
    """Size of each edition: clauses, words, and how long clauses are."""
    rows = []
    for document, label in ADB_SERIES:
        version = find_version(document, label)
        clauses = get_clauses(version["id"])
        words = [len(c["content"].split()) for c in clauses]
        rows.append({
            "edition": label,
            "clauses": len(clauses),
            "words": sum(words),
            "mean_clause_words": round(sum(words) / len(words), 1) if words else 0,
            "clauses_over_180_words": sum(1 for w in words if w > 180),
        })
    return rows


def _transitions(comparator: SemanticComparator) -> list[dict]:
    """Clause-level change between each consecutive pair of editions."""
    rows = []

    for (document, older), (_, newer) in zip(ADB_SERIES, ADB_SERIES[1:]):
        baseline = find_version(document, older)
        revision = find_version(document, newer)

        report = comparator.compare(
            get_clauses(baseline["id"]), get_clauses(revision["id"]),
            _ref(baseline), _ref(revision),
            strategy=ALIGNMENT_IDENTIFIER,
        )
        summary = report.summary

        # Where did the change land? Count changed clauses per section.
        churn: Counter[str] = Counter()
        for row in report.comparisons:
            if row.change_type == ChangeType.UNCHANGED:
                continue
            number = row.v1.clause_number if row.v1 else row.v2.clause_number
            churn[_section_of(number)] += 1

        rows.append({
            "from": older,
            "to": newer,
            "clauses_compared": summary.total_clauses,
            "unchanged": summary.unchanged,
            "minor_edits": summary.minor_edits,
            "significant_changes": summary.significant_changes,
            "added": summary.added,
            "removed": summary.removed,
            "change_rate_percent": round(summary.change_rate, 1),
            "words_added": summary.words_added,
            "words_removed": summary.words_removed,
            "net_words": summary.words_added - summary.words_removed,
            "most_changed_sections": [
                {"section": section, "changed_clauses": count}
                for section, count in churn.most_common(8)
            ],
        })

    return rows


def _register_attention() -> dict:
    """
    Which parts of the guidance the regulator keeps returning to.

    Counted from the published registers rather than from text differences, so
    a section that is rewritten once counts once, and a section amended in four
    separate rounds counts four times.
    """
    per_register = []
    section_counts: Counter[str] = Counter()
    operation_counts: Counter[str] = Counter()
    reference_rounds: Counter[str] = Counter()

    for label, key in REGISTERS:
        try:
            amendments = load_booklet(key)
        except FileNotFoundError:
            continue

        volume_one = [a for a in amendments if a.volume in (1, None)]
        sections = Counter(_section_of(a.reference) for a in volume_one)

        for amendment in volume_one:
            section_counts[_section_of(amendment.reference)] += 1
            operation_counts[amendment.operation] += 1
        for reference in {a.reference for a in volume_one}:
            reference_rounds[reference] += 1

        per_register.append({
            "register": label,
            "amendments": len(volume_one),
            "sections_touched": len(sections),
            "top_sections": [
                {"section": s, "amendments": n} for s, n in sections.most_common(4)
            ],
        })

    return {
        "per_register": per_register,
        "sections_by_total_amendments": [
            {"section": s, "amendments": n} for s, n in section_counts.most_common(10)
        ],
        "operations": dict(operation_counts),
        "clauses_amended_in_multiple_rounds": [
            {"reference": r, "rounds": n}
            for r, n in reference_rounds.most_common(12) if n > 1
        ],
    }


def _jurisdiction_sizes() -> list[dict]:
    """How the four jurisdictions compare in bulk — the guidance is not equal."""
    grouped: dict[str, dict] = {}

    for version in list_all_versions():
        code = version["country_code"]
        if code == "INT":
            continue
        clauses = get_clauses(version["id"])
        words = sum(len(c["content"].split()) for c in clauses)

        entry = grouped.setdefault(code, {
            "country_code": code,
            "country_name": version["country_name"],
            "editions": 0,
            "clauses": 0,
            "words": 0,
        })
        entry["editions"] += 1
        entry["clauses"] += len(clauses)
        entry["words"] += words

    return sorted(grouped.values(), key=lambda row: -row["words"])


def render_evolution(result: dict) -> str:
    """Format the study for the terminal."""
    lines: list[str] = []

    lines.append("\nEdition sizes — Approved Document B, Volume 1")
    lines.append("=" * 60)
    lines.append(f"  {'edition':<20}{'clauses':>9}{'words':>10}{'mean/clause':>13}{'>180 words':>12}")
    for row in result["series"]:
        lines.append(f"  {row['edition']:<20}{row['clauses']:>9}{row['words']:>10}"
                     f"{row['mean_clause_words']:>13}{row['clauses_over_180_words']:>12}")

    lines.append("\nWhat changed between editions")
    lines.append("=" * 60)
    for row in result["transitions"]:
        lines.append(f"\n  {row['from']} → {row['to']}")
        lines.append(f"    {row['clauses_compared']} clauses compared · "
                     f"{row['change_rate_percent']}% changed")
        lines.append(f"    unchanged {row['unchanged']} · minor {row['minor_edits']} · "
                     f"significant {row['significant_changes']} · "
                     f"added {row['added']} · removed {row['removed']}")
        lines.append(f"    words +{row['words_added']:,} / -{row['words_removed']:,} "
                     f"(net {row['net_words']:+,})")
        top = ", ".join(f"{s['section']} ({s['changed_clauses']})"
                        for s in row["most_changed_sections"][:5])
        lines.append(f"    most changed: {top}")

    attention = result["register_attention"]
    lines.append("\nWhere the regulator keeps returning (published registers)")
    lines.append("=" * 60)
    lines.append(f"  {'register':<14}{'amendments':>12}{'sections':>10}")
    for row in attention["per_register"]:
        lines.append(f"  {row['register']:<14}{row['amendments']:>12}{row['sections_touched']:>10}")

    lines.append("\n  sections by total amendments across all registers:")
    for row in attention["sections_by_total_amendments"][:8]:
        lines.append(f"    {row['section']:<16}{row['amendments']:>4}")

    lines.append(f"\n  operations: {attention['operations']}")

    repeats = attention["clauses_amended_in_multiple_rounds"]
    if repeats:
        lines.append("  clauses amended in more than one round: " +
                     ", ".join(f"{r['reference']} ({r['rounds']}x)" for r in repeats[:10]))

    lines.append("\nGuidance bulk by jurisdiction")
    lines.append("=" * 60)
    lines.append(f"  {'jurisdiction':<24}{'editions':>10}{'clauses':>9}{'words':>10}")
    for row in result["jurisdiction_sizes"]:
        lines.append(f"  {row['country_name']:<24}{row['editions']:>10}"
                     f"{row['clauses']:>9}{row['words']:>10}")

    return "\n".join(lines)
