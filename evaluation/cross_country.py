"""
Challenges in Cross-Country Comparison
──────────────────────────────────────
What makes comparing fire safety regulations across jurisdictions hard, stated
as measurements rather than impressions.

Four obstacles are quantified:

    Numbering.    Clause identifiers do not correspond between jurisdictions,
                  so the cheap exact-match alignment is unavailable.
    Confidence.   Matching on meaning produces weaker, flatter pairings than
                  matching within one instrument, which is what raises the
                  false-pairing rate.
    Coverage.     Each jurisdiction says things the others do not, so a large
                  share of clauses have no counterpart at all.
    Vocabulary.   The same requirement is written in different technical terms,
                  which is what defeats keyword search across jurisdictions and
                  degrades embedding similarity.

The same-jurisdiction pair is included throughout as a control: every number
means more when read against what the method achieves when the documents *are*
comparable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from comparison.alignment import identifier_overlap
from comparison.engine import SemanticComparator
from comparison.report import ChangeType
from config import ALIGNMENT_SEMANTIC
from database.operations import get_clauses
from evaluation.experiments import _ref, find_version
from evaluation.metrics import describe

# Pairs to study. The first is the within-jurisdiction control.
PAIRS = [
    ("control: England & Wales, two editions",
     ("Volume 1: Dwellings", "2019 edition"),
     ("Volume 1: Dwellings", "2025 amendments")),
    ("England & Wales vs Scotland",
     ("Volume 1: Dwellings", "2025 amendments"),
     ("Technical Handbook — Domestic", "2022 edition")),
    ("England & Wales vs Northern Ireland",
     ("Volume 1: Dwellings", "2025 amendments"),
     ("Technical Booklet E", "October 2012")),
    ("Northern Ireland vs Republic of Ireland",
     ("Technical Booklet E", "October 2012"),
     ("Technical Guidance Document B — Volume 1", "2024 edition")),
]

# Terms that name the same idea differently, or that one jurisdiction uses and
# another does not. Chosen from the fire safety vocabulary an auditor searches.
TERM_FAMILIES = {
    "dwelling": ["dwellinghouse", "dwelling house", "dwelling"],
    "escape distance": ["travel distance", "escape route", "means of escape"],
    "protected stair": ["protected stairway", "protected zone", "protected shaft",
                        "protected corridor"],
    "fire door": ["fire doorset", "fire door", "self-closing device"],
    "suppression": ["sprinkler", "suppression system", "residential sprinkler"],
    "compartment": ["compartment wall", "compartment floor", "compartmentation"],
    "external wall": ["external wall", "cladding", "combustible material"],
    "alarm": ["fire detection", "smoke alarm", "fire alarm"],
}

JURISDICTION_DOCS = [
    ("EW", "Volume 1: Dwellings", "2025 amendments"),
    ("SC", "Technical Handbook — Domestic", "2022 edition"),
    ("NI", "Technical Booklet E", "October 2012"),
    ("IE", "Technical Guidance Document B — Volume 1", "2024 edition"),
]


@dataclass
class PairResult:
    label: str
    left: str
    right: str
    cross_country: bool
    identifier_overlap: float
    clauses_left: int
    clauses_right: int
    matched: int
    unmatched_left: int
    unmatched_right: int
    match_rate: float
    match_score: dict
    similarity: dict
    duration_seconds: float


def run_cross_country(comparator: SemanticComparator) -> dict:
    """Quantify the four obstacles."""
    pairs = [_study_pair(comparator, *entry) for entry in PAIRS]

    return {
        "study": "Challenges in cross-country comparison",
        "pairs": [p.__dict__ for p in pairs],
        "numbering": _numbering_schemes(),
        "vocabulary": _vocabulary_divergence(),
    }


def _study_pair(comparator: SemanticComparator, label, left_spec, right_spec) -> PairResult:
    left = find_version(*left_spec)
    right = find_version(*right_spec)

    clauses_left = get_clauses(left["id"])
    clauses_right = get_clauses(right["id"])

    # Semantic alignment is forced for every pair, including the control, so
    # the comparison is between documents rather than between methods.
    report = comparator.compare(
        clauses_left, clauses_right, _ref(left), _ref(right),
        strategy=ALIGNMENT_SEMANTIC,
    )

    matched = [r for r in report.comparisons if r.v1 and r.v2]
    unmatched_left = sum(1 for r in report.comparisons if r.change_type == ChangeType.REMOVED)
    unmatched_right = sum(1 for r in report.comparisons if r.change_type == ChangeType.ADDED)

    smaller = min(len(clauses_left), len(clauses_right))

    return PairResult(
        label=label,
        left=f"{left['country_code']} {left['document_name']} — {left['version_label']}",
        right=f"{right['country_code']} {right['document_name']} — {right['version_label']}",
        cross_country=left["country_code"] != right["country_code"],
        identifier_overlap=round(identifier_overlap(clauses_left, clauses_right), 4),
        clauses_left=len(clauses_left),
        clauses_right=len(clauses_right),
        matched=len(matched),
        unmatched_left=unmatched_left,
        unmatched_right=unmatched_right,
        match_rate=round(len(matched) / smaller, 4) if smaller else 0.0,
        match_score=describe([r.match_score for r in matched if r.match_score is not None]),
        similarity=describe([r.similarity_score for r in matched
                             if r.similarity_score is not None]),
        duration_seconds=round(report.duration_seconds, 1),
    )


def _numbering_schemes() -> list[dict]:
    """
    The shape of each jurisdiction's clause identifiers.

    Reported as normalised patterns — "N.N", "Standard N.N" — because it is the
    shapes, not the values, that fail to correspond across borders.
    """
    rows = []

    for code, document, label in JURISDICTION_DOCS:
        version = find_version(document, label)
        clauses = get_clauses(version["id"])

        shapes: dict[str, int] = {}
        depths: list[int] = []
        for clause in clauses:
            number = clause["clause_number"]
            shape = re.sub(r"\d+", "N", number)
            shapes[shape] = shapes.get(shape, 0) + 1
            depths.append(number.count(".") + 1)

        rows.append({
            "country_code": code,
            "document": version["document_name"],
            "clauses": len(clauses),
            "distinct_shapes": len(shapes),
            "top_shapes": sorted(shapes.items(), key=lambda kv: -kv[1])[:5],
            "mean_depth": round(sum(depths) / len(depths), 2) if depths else 0,
        })

    return rows


def _vocabulary_divergence() -> dict:
    """
    How often each jurisdiction uses each term.

    Rates are per 10,000 words so documents of different lengths compare. A
    term used heavily in one jurisdiction and never in another is a term an
    auditor cannot search across borders.
    """
    per_jurisdiction: dict[str, dict] = {}

    for code, document, label in JURISDICTION_DOCS:
        version = find_version(document, label)
        text = " ".join(c["content"] for c in get_clauses(version["id"])).casefold()
        total_words = max(1, len(text.split()))

        counts: dict[str, dict[str, float]] = {}
        for family, terms in TERM_FAMILIES.items():
            counts[family] = {
                term: round(text.count(term) * 10_000 / total_words, 2)
                for term in terms
            }

        per_jurisdiction[code] = {
            "document": version["document_name"],
            "words": total_words,
            "rates_per_10k_words": counts,
        }

    # A term is "jurisdiction-specific" when one jurisdiction uses it and at
    # least one other never does. Those are the search failures.
    exclusive: list[dict] = []
    for family, terms in TERM_FAMILIES.items():
        for term in terms:
            rates = {
                code: data["rates_per_10k_words"][family][term]
                for code, data in per_jurisdiction.items()
            }
            users = [code for code, rate in rates.items() if rate > 0]
            absent = [code for code, rate in rates.items() if rate == 0]
            if users and absent:
                exclusive.append({
                    "term": term,
                    "family": family,
                    "used_by": users,
                    "absent_from": absent,
                    "rates": rates,
                })

    return {
        "per_jurisdiction": per_jurisdiction,
        "jurisdiction_specific_terms": exclusive,
    }


def render_cross_country(result: dict) -> str:
    """Format the study for the terminal."""
    lines: list[str] = []

    lines.append("\nAlignment across jurisdictions (semantic matching throughout)")
    lines.append("=" * 78)
    lines.append(f"  {'pair':<42}{'id overlap':>11}{'matched':>9}{'match rate':>12}")
    for pair in result["pairs"]:
        lines.append(f"  {pair['label'][:41]:<42}{pair['identifier_overlap']:>11.3f}"
                     f"{pair['matched']:>9}{pair['match_rate']:>12.3f}")

    lines.append("\n  match confidence and similarity, by pair:")
    for pair in result["pairs"]:
        score, similarity = pair["match_score"], pair["similarity"]
        lines.append(f"    {pair['label'][:44]:<46}")
        lines.append(f"      match  median {score.get('median')}  "
                     f"p25 {score.get('p25')}  p75 {score.get('p75')}")
        lines.append(f"      cosine median {similarity.get('median')}  "
                     f"unmatched {pair['unmatched_left']}+{pair['unmatched_right']}")

    lines.append("\nNumbering schemes")
    lines.append("=" * 78)
    lines.append(f"  {'':<5}{'clauses':>9}{'shapes':>8}{'depth':>7}  most common")
    for row in result["numbering"]:
        shapes = ", ".join(f"{shape} ({count})" for shape, count in row["top_shapes"][:3])
        lines.append(f"  {row['country_code']:<5}{row['clauses']:>9}"
                     f"{row['distinct_shapes']:>8}{row['mean_depth']:>7}  {shapes}")

    lines.append("\nTerminology (uses per 10,000 words)")
    lines.append("=" * 78)
    vocabulary = result["vocabulary"]
    codes = list(vocabulary["per_jurisdiction"].keys())
    lines.append(f"  {'term':<28}" + "".join(code.rjust(9) for code in codes))
    for family, terms in TERM_FAMILIES.items():
        for term in terms:
            rates = [vocabulary["per_jurisdiction"][code]["rates_per_10k_words"][family][term]
                     for code in codes]
            if not any(rates):
                continue
            lines.append(f"  {term:<28}" + "".join(f"{rate:>9.1f}" for rate in rates))

    exclusive = vocabulary["jurisdiction_specific_terms"]
    lines.append(f"\n  terms absent from at least one jurisdiction: {len(exclusive)}")
    for entry in exclusive[:10]:
        lines.append(f"    {entry['term']:<26} used by {','.join(entry['used_by'])}"
                     f"  absent from {','.join(entry['absent_from'])}")

    return "\n".join(lines)
