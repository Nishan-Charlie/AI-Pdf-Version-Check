"""
Comparison Report
─────────────────
The shape of a finished comparison.

A row holds both sides independently, because in a cross-country comparison
the two clauses being shown do not share a number, a title, or a section — only
a subject.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ChangeType(Enum):
    """How a clause differs between the two versions."""

    UNCHANGED = "Unchanged"
    MINOR_EDIT = "Minor Edit"
    SIGNIFICANT_CHANGE = "Significant Change"
    ADDED = "Added"
    REMOVED = "Removed"


# Ordered for display: the types an auditor acts on come first.
CHANGE_TYPE_ORDER = [
    ChangeType.SIGNIFICANT_CHANGE,
    ChangeType.ADDED,
    ChangeType.REMOVED,
    ChangeType.MINOR_EDIT,
    ChangeType.UNCHANGED,
]


@dataclass
class ClauseSide:
    """One version's half of a comparison row."""

    clause_number: str
    title: Optional[str]
    section: Optional[str]
    content: str
    ordinal: int

    def as_dict(self) -> dict:
        return {
            "clause_number": self.clause_number,
            "title": self.title,
            "section": self.section,
            "content": self.content,
            "ordinal": self.ordinal,
        }


@dataclass
class ClauseComparison:
    """One aligned clause pair, with its redline already rendered."""

    index: int
    change_type: ChangeType
    v1: Optional[ClauseSide]
    v2: Optional[ClauseSide]
    redline: dict
    similarity_score: Optional[float] = None   # embedding cosine
    match_score: Optional[float] = None        # alignment confidence
    match_method: str = "identifier"

    @property
    def label(self) -> str:
        """What to call this row: both numbers when they differ."""
        left = self.v1.clause_number if self.v1 else None
        right = self.v2.clause_number if self.v2 else None
        if left and right and left != right:
            return f"{left} → {right}"
        return left or right or "—"

    def as_dict(self) -> dict:
        return {
            "index": self.index,
            "label": self.label,
            "change_type": self.change_type.value,
            "similarity_score": self.similarity_score,
            "match_score": self.match_score,
            "match_method": self.match_method,
            "v1": self.v1.as_dict() if self.v1 else None,
            "v2": self.v2.as_dict() if self.v2 else None,
            "redline": self.redline,
        }


@dataclass
class ComparisonSummary:
    """Aggregate counts for a comparison."""

    total_clauses: int = 0
    unchanged: int = 0
    minor_edits: int = 0
    significant_changes: int = 0
    added: int = 0
    removed: int = 0
    words_added: int = 0
    words_removed: int = 0

    @property
    def changed(self) -> int:
        return self.minor_edits + self.significant_changes + self.added + self.removed

    @property
    def change_rate(self) -> float:
        """Percentage of clauses that differ in any way."""
        if self.total_clauses == 0:
            return 0.0
        return (self.changed / self.total_clauses) * 100

    def as_dict(self) -> dict:
        return {
            "total_clauses": self.total_clauses,
            "unchanged": self.unchanged,
            "minor_edits": self.minor_edits,
            "significant_changes": self.significant_changes,
            "added": self.added,
            "removed": self.removed,
            "words_added": self.words_added,
            "words_removed": self.words_removed,
            "changed": self.changed,
            "change_rate": round(self.change_rate, 2),
        }


@dataclass
class VersionRef:
    """Which document edition a side of the comparison came from."""

    version_id: Optional[int]
    document_name: str
    version_label: str
    country_code: str
    country_name: str

    def as_dict(self) -> dict:
        return {
            "version_id": self.version_id,
            "document_name": self.document_name,
            "version_label": self.version_label,
            "country_code": self.country_code,
            "country_name": self.country_name,
        }


@dataclass
class ComparisonReport:
    """A finished comparison between two document versions."""

    v1: VersionRef
    v2: VersionRef
    alignment_method: str
    comparisons: list[ClauseComparison] = field(default_factory=list)
    summary: ComparisonSummary = field(default_factory=ComparisonSummary)
    identifier_overlap: float = 0.0
    duration_seconds: float = 0.0
    # Which encoder produced the similarity scores. Results are not comparable
    # across models, so a report has to say which one it came from.
    model: str = ""

    @property
    def is_cross_country(self) -> bool:
        return self.v1.country_code != self.v2.country_code

    def compute_summary(self) -> None:
        """Recalculate counts from the comparison rows."""
        summary = ComparisonSummary(total_clauses=len(self.comparisons))

        tally = {
            ChangeType.UNCHANGED: "unchanged",
            ChangeType.MINOR_EDIT: "minor_edits",
            ChangeType.SIGNIFICANT_CHANGE: "significant_changes",
            ChangeType.ADDED: "added",
            ChangeType.REMOVED: "removed",
        }

        for comparison in self.comparisons:
            attribute = tally[comparison.change_type]
            setattr(summary, attribute, getattr(summary, attribute) + 1)
            summary.words_added += comparison.redline.get("words_added", 0)
            summary.words_removed += comparison.redline.get("words_removed", 0)

        self.summary = summary

    def as_dict(self) -> dict:
        return {
            "v1": self.v1.as_dict(),
            "v2": self.v2.as_dict(),
            "alignment_method": self.alignment_method,
            "model": self.model,
            "identifier_overlap": round(self.identifier_overlap, 3),
            "is_cross_country": self.is_cross_country,
            "duration_seconds": round(self.duration_seconds, 2),
            "summary": self.summary.as_dict(),
            "comparisons": [c.as_dict() for c in self.comparisons],
        }

    def to_rows(self) -> list[dict]:
        """Flat rows for CSV export."""
        rows = []
        for comparison in self.comparisons:
            left, right = comparison.v1, comparison.v2
            rows.append({
                "Change Type": comparison.change_type.value,
                f"{self.v1.version_label} Clause": left.clause_number if left else "",
                f"{self.v1.version_label} Section": (left.section or "") if left else "",
                f"{self.v1.version_label} Text": left.content if left else "(not present)",
                f"{self.v2.version_label} Clause": right.clause_number if right else "",
                f"{self.v2.version_label} Section": (right.section or "") if right else "",
                f"{self.v2.version_label} Text": right.content if right else "(not present)",
                "Similarity": (
                    f"{comparison.similarity_score:.4f}"
                    if comparison.similarity_score is not None else "N/A"
                ),
                "Match Confidence": (
                    f"{comparison.match_score:.4f}"
                    if comparison.match_score is not None else "N/A"
                ),
                "Words Added": comparison.redline.get("words_added", 0),
                "Words Removed": comparison.redline.get("words_removed", 0),
            })
        return rows
