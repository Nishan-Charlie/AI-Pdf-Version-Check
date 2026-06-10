"""
Comparison Report Data Structures
──────────────────────────────────
Dataclasses for representing clause-level semantic diffs between
two document versions.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ChangeType(Enum):
    """Classification of change between two clause versions."""
    UNCHANGED = "Unchanged"
    MINOR_EDIT = "Minor Edit"
    SIGNIFICANT_CHANGE = "Significant Change"
    ADDED = "Added"
    REMOVED = "Removed"


# Color mapping for the Streamlit UI
CHANGE_TYPE_COLORS = {
    ChangeType.UNCHANGED: "#2ecc71",          # Green
    ChangeType.MINOR_EDIT: "#f39c12",         # Amber
    ChangeType.SIGNIFICANT_CHANGE: "#e74c3c", # Red
    ChangeType.ADDED: "#3498db",              # Blue
    ChangeType.REMOVED: "#9b59b6",            # Purple
}

CHANGE_TYPE_BG_COLORS = {
    ChangeType.UNCHANGED: "rgba(46, 204, 113, 0.1)",
    ChangeType.MINOR_EDIT: "rgba(243, 156, 18, 0.15)",
    ChangeType.SIGNIFICANT_CHANGE: "rgba(231, 76, 60, 0.15)",
    ChangeType.ADDED: "rgba(52, 152, 219, 0.15)",
    ChangeType.REMOVED: "rgba(155, 89, 182, 0.15)",
}


@dataclass
class ClauseComparison:
    """Result of comparing a single clause across two versions."""
    clause_number: str
    title: Optional[str]
    content_v1: Optional[str]  # None if clause was ADDED in v2
    content_v2: Optional[str]  # None if clause was REMOVED in v2
    similarity_score: Optional[float]  # None for ADDED/REMOVED
    change_type: ChangeType

    @property
    def color(self) -> str:
        return CHANGE_TYPE_COLORS[self.change_type]

    @property
    def bg_color(self) -> str:
        return CHANGE_TYPE_BG_COLORS[self.change_type]


@dataclass
class ComparisonSummary:
    """Aggregate statistics for a comparison report."""
    total_clauses: int = 0
    unchanged: int = 0
    minor_edits: int = 0
    significant_changes: int = 0
    added: int = 0
    removed: int = 0

    @property
    def change_rate(self) -> float:
        """Percentage of clauses with any change."""
        if self.total_clauses == 0:
            return 0.0
        changed = self.minor_edits + self.significant_changes + self.added + self.removed
        return (changed / self.total_clauses) * 100


@dataclass
class ComparisonReport:
    """Full comparison report between two document versions."""
    document_name: str
    version_v1_label: str
    version_v2_label: str
    comparisons: list[ClauseComparison] = field(default_factory=list)
    summary: ComparisonSummary = field(default_factory=ComparisonSummary)

    def compute_summary(self):
        """Recalculate summary stats from the comparisons list."""
        self.summary = ComparisonSummary()

        # Total unique clauses = all compared
        self.summary.total_clauses = len(self.comparisons)

        for comp in self.comparisons:
            if comp.change_type == ChangeType.UNCHANGED:
                self.summary.unchanged += 1
            elif comp.change_type == ChangeType.MINOR_EDIT:
                self.summary.minor_edits += 1
            elif comp.change_type == ChangeType.SIGNIFICANT_CHANGE:
                self.summary.significant_changes += 1
            elif comp.change_type == ChangeType.ADDED:
                self.summary.added += 1
            elif comp.change_type == ChangeType.REMOVED:
                self.summary.removed += 1

    def to_dataframe_rows(self) -> list[dict]:
        """Convert comparisons to a list of flat dicts for DataFrame/CSV export."""
        rows = []
        for c in self.comparisons:
            rows.append({
                "Clause #": c.clause_number,
                "Title": c.title or "",
                "Version 1 Content": c.content_v1 or "(not present)",
                "Version 2 Content": c.content_v2 or "(not present)",
                "Similarity": f"{c.similarity_score:.4f}" if c.similarity_score is not None else "N/A",
                "Change Type": c.change_type.value,
            })
        return rows
