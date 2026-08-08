"""
Evaluation Metrics
──────────────────
Plain implementations of the scores the accuracy study reports. No sklearn
dependency here on purpose: these are small enough to read, and a reader
checking the dissertation's numbers can follow the arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Sequence


@dataclass
class BinaryScore:
    """Precision, recall, and F1 for a single yes/no decision."""

    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int = 0

    @property
    def predicted_positive(self) -> int:
        return self.true_positives + self.false_positives

    @property
    def actual_positive(self) -> int:
        return self.true_positives + self.false_negatives

    @property
    def precision(self) -> float:
        """Of what the system flagged, how much should have been flagged."""
        return self.true_positives / self.predicted_positive if self.predicted_positive else 0.0

    @property
    def recall(self) -> float:
        """Of what should have been flagged, how much the system found."""
        return self.true_positives / self.actual_positive if self.actual_positive else 0.0

    @property
    def f1(self) -> float:
        denominator = self.precision + self.recall
        return 2 * self.precision * self.recall / denominator if denominator else 0.0

    def as_dict(self) -> dict:
        return {
            "true_positives": self.true_positives,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
            "true_negatives": self.true_negatives,
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
        }


def score_sets(predicted: set, actual: set, universe: set | None = None) -> BinaryScore:
    """
    Compare a predicted set against a reference set.

    `universe` is the population both sets are drawn from. Supplying it lets
    true negatives be counted, which matters when reporting how much of a
    document the system correctly left alone.
    """
    true_positives = len(predicted & actual)
    false_positives = len(predicted - actual)
    false_negatives = len(actual - predicted)

    true_negatives = 0
    if universe is not None:
        true_negatives = len(universe - predicted - actual)

    return BinaryScore(true_positives, false_positives, false_negatives, true_negatives)


@dataclass
class ConfusionMatrix:
    """Counts of predicted label against true label, over a fixed label set."""

    labels: Sequence[str]
    counts: dict[tuple[str, str], int] = field(default_factory=dict)

    def add(self, true_label: str, predicted_label: str) -> None:
        key = (true_label, predicted_label)
        self.counts[key] = self.counts.get(key, 0) + 1

    def get(self, true_label: str, predicted_label: str) -> int:
        return self.counts.get((true_label, predicted_label), 0)

    @property
    def total(self) -> int:
        return sum(self.counts.values())

    @property
    def accuracy(self) -> float:
        if self.total == 0:
            return 0.0
        correct = sum(self.get(label, label) for label in self.labels)
        return correct / self.total

    def per_label(self) -> dict[str, BinaryScore]:
        """One-vs-rest scores for every label."""
        scores: dict[str, BinaryScore] = {}
        for label in self.labels:
            true_positives = self.get(label, label)
            false_positives = sum(
                self.get(other, label) for other in self.labels if other != label
            )
            false_negatives = sum(
                self.get(label, other) for other in self.labels if other != label
            )
            true_negatives = self.total - true_positives - false_positives - false_negatives
            scores[label] = BinaryScore(
                true_positives, false_positives, false_negatives, true_negatives
            )
        return scores

    def macro_f1(self) -> float:
        """Unweighted mean F1 — every class counts the same, however rare."""
        scores = self.per_label()
        present = [s for label, s in scores.items() if s.actual_positive > 0]
        return sum(s.f1 for s in present) / len(present) if present else 0.0

    def weighted_f1(self) -> float:
        """Mean F1 weighted by how often each class actually occurs."""
        scores = self.per_label()
        total = sum(s.actual_positive for s in scores.values())
        if total == 0:
            return 0.0
        return sum(s.f1 * s.actual_positive for s in scores.values()) / total

    def render(self) -> str:
        """A fixed-width table: rows are truth, columns are prediction."""
        width = max(14, max((len(label) for label in self.labels), default=8) + 2)
        header = "true \\ predicted".ljust(width) + "".join(
            label[:width - 2].rjust(width) for label in self.labels
        )
        lines = [header, "-" * len(header)]

        for true_label in self.labels:
            row = true_label.ljust(width)
            for predicted_label in self.labels:
                row += str(self.get(true_label, predicted_label)).rjust(width)
            lines.append(row)

        return "\n".join(lines)

    def as_dict(self) -> dict:
        return {
            "labels": list(self.labels),
            "matrix": {
                f"{true}|{predicted}": count
                for (true, predicted), count in sorted(self.counts.items())
            },
            "accuracy": round(self.accuracy, 4),
            "macro_f1": round(self.macro_f1(), 4),
            "weighted_f1": round(self.weighted_f1(), 4),
            "per_label": {label: score.as_dict() for label, score in self.per_label().items()},
        }


def cohens_kappa(matrix: ConfusionMatrix) -> float:
    """
    Chance-corrected agreement between two labellings.

    Used for annotator-versus-system agreement, where raw accuracy flatters a
    system on a skewed label distribution — most clauses are unchanged, so
    always guessing "unchanged" scores well and agrees with nobody.
    """
    total = matrix.total
    if total == 0:
        return 0.0

    observed = matrix.accuracy

    expected = 0.0
    for label in matrix.labels:
        true_marginal = sum(matrix.get(label, other) for other in matrix.labels)
        predicted_marginal = sum(matrix.get(other, label) for other in matrix.labels)
        expected += (true_marginal / total) * (predicted_marginal / total)

    if expected >= 1.0:
        return 1.0
    return (observed - expected) / (1 - expected)


def describe(values: Iterable[float]) -> dict:
    """Summary statistics for a distribution of scores."""
    ordered = sorted(values)
    if not ordered:
        return {"count": 0}

    def quantile(fraction: float) -> float:
        position = fraction * (len(ordered) - 1)
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        weight = position - lower
        return ordered[lower] * (1 - weight) + ordered[upper] * weight

    return {
        "count": len(ordered),
        "mean": round(sum(ordered) / len(ordered), 4),
        "min": round(ordered[0], 4),
        "p25": round(quantile(0.25), 4),
        "median": round(quantile(0.50), 4),
        "p75": round(quantile(0.75), 4),
        "max": round(ordered[-1], 4),
    }
