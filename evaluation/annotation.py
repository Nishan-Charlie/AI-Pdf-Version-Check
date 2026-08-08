"""
Manual Annotation Harness
─────────────────────────
Prepares a sample of clause pairs for a human to label, and scores the system
against the labels once they come back.

The sheet is **blind**: it carries the two clause texts and nothing else. The
system's own prediction is written to a separate key file, joined by row id
after annotation. An annotator who can see the machine's answer tends to agree
with it, and an evaluation built on that agreement measures nothing.

Nothing in this module invents labels. `build_sample` writes empty columns;
they stay empty until a person fills them in.

    python -m evaluation.run annotate --size 150
    …label evaluation/annotations/<name>.csv by hand…
    python -m evaluation.run score-annotations --sheet evaluation/annotations/<name>.csv
"""

from __future__ import annotations

import csv
import os
import random
from dataclasses import dataclass
from typing import Optional

from comparison.report import ChangeType, ComparisonReport
from config import BASE_DIR
from evaluation.metrics import ConfusionMatrix, cohens_kappa

ANNOTATION_DIR = os.path.join(BASE_DIR, "evaluation", "annotations")

LABELS = [t.value for t in ChangeType]

SHEET_COLUMNS = [
    "id",
    "clause_v1",
    "clause_v2",
    "section",
    "text_v1",
    "text_v2",
    "annotator_change_type",
    "annotator_alignment_ok",
    "annotator_notes",
]

KEY_COLUMNS = [
    "id",
    "system_change_type",
    "system_similarity",
    "system_match_score",
    "system_alignment_method",
    "word_change_ratio",
]

PROTOCOL = """\
Annotation protocol — clause change classification
==================================================

For each row, read the two clause texts and fill in two columns. Do not consult
the system's output; the point of the exercise is an independent judgement.

annotator_change_type — one of:

  Unchanged            The two texts impose the same requirement in the same
                       terms. Differences in spacing, hyphenation, or line
                       breaks introduced by typesetting count as Unchanged.

  Minor Edit           The requirement is the same, but the wording changed:
                       clarification, restructuring, a cross-reference update,
                       or a change of terminology that does not change what a
                       building must do.

  Significant Change   What the building must do is different: a changed
                       measurement, threshold, classification, or scope; a new
                       obligation; a removed exemption.

  Added                The clause exists only in version 2.

  Removed              The clause exists only in version 1.

annotator_alignment_ok — yes / no

  Whether these two clauses are counterparts at all. Answer "no" when the pair
  is mismatched — the system paired two clauses that are about different
  things. Leave blank for Added and Removed rows, which have only one side.

annotator_notes — optional; anything the labels cannot capture. Rows you are
unsure about are worth flagging here, and can be reported separately.

A note on sampling: rows are drawn evenly across the system's predicted
classes so that rare ones (Added, Removed) appear often enough to score. That
makes the sheet's class balance artificial, so report per-class precision and
recall rather than overall accuracy.
"""


@dataclass
class AnnotationScore:
    sheet: str
    annotated_rows: int
    skipped_rows: int
    change_type: dict
    kappa: float
    alignment: dict
    disagreements: list[dict]

    def as_dict(self) -> dict:
        return {
            "experiment": "E4 system vs manual annotation",
            "sheet": self.sheet,
            "annotated_rows": self.annotated_rows,
            "skipped_rows": self.skipped_rows,
            "change_type": self.change_type,
            "cohens_kappa": round(self.kappa, 4),
            "alignment": self.alignment,
            "disagreements": self.disagreements,
        }


def build_sample(
    report: ComparisonReport,
    name: str,
    size: int = 150,
    seed: int = 20260808,
    max_chars: int = 1200,
) -> tuple[str, str, str]:
    """
    Write a blind annotation sheet, its answer key, and the protocol.

    Rows are drawn evenly across the system's predicted classes so the rare
    ones are represented; within a class the draw is random under `seed`, so
    the sample is reproducible.

    Returns:
        (sheet path, key path, protocol path)
    """
    os.makedirs(ANNOTATION_DIR, exist_ok=True)

    buckets: dict[str, list] = {label: [] for label in LABELS}
    for row in report.comparisons:
        buckets[row.change_type.value].append(row)

    rng = random.Random(seed)
    for rows in buckets.values():
        rng.shuffle(rows)

    # Even quota per class, redistributing what rare classes cannot fill.
    selected = []
    populated = [label for label in LABELS if buckets[label]]
    quota = max(1, size // max(1, len(populated)))

    for label in populated:
        selected.extend(buckets[label][:quota])

    if len(selected) < size:
        remainder = [
            row for label in populated for row in buckets[label][quota:]
        ]
        rng.shuffle(remainder)
        selected.extend(remainder[: size - len(selected)])

    rng.shuffle(selected)  # so the sheet's order does not telegraph the class
    selected = selected[:size]

    sheet_path = os.path.join(ANNOTATION_DIR, f"{name}.csv")
    key_path = os.path.join(ANNOTATION_DIR, f"{name}.key.csv")
    protocol_path = os.path.join(ANNOTATION_DIR, "PROTOCOL.md")

    with open(sheet_path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SHEET_COLUMNS)
        writer.writeheader()
        for index, row in enumerate(selected):
            writer.writerow({
                "id": index,
                "clause_v1": row.v1.clause_number if row.v1 else "",
                "clause_v2": row.v2.clause_number if row.v2 else "",
                "section": (row.v2.section if row.v2 else None) or (row.v1.section if row.v1 else "") or "",
                "text_v1": _trim(row.v1.content if row.v1 else "", max_chars),
                "text_v2": _trim(row.v2.content if row.v2 else "", max_chars),
                "annotator_change_type": "",
                "annotator_alignment_ok": "",
                "annotator_notes": "",
            })

    with open(key_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=KEY_COLUMNS)
        writer.writeheader()
        for index, row in enumerate(selected):
            writer.writerow({
                "id": index,
                "system_change_type": row.change_type.value,
                "system_similarity": row.similarity_score if row.similarity_score is not None else "",
                "system_match_score": row.match_score if row.match_score is not None else "",
                "system_alignment_method": row.match_method,
                "word_change_ratio": row.redline.get("word_change_ratio", 0.0),
            })

    with open(protocol_path, "w", encoding="utf-8") as handle:
        handle.write(PROTOCOL)

    return sheet_path, key_path, protocol_path


def _trim(text: str, limit: int) -> str:
    text = (text or "").replace("\r", " ")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def score_annotations(sheet_path: str, key_path: Optional[str] = None) -> AnnotationScore:
    """
    Score the system against a completed sheet.

    Rows left blank are counted as skipped and excluded — an unlabelled row is
    not evidence either way.
    """
    key_path = key_path or sheet_path.replace(".csv", ".key.csv")

    if not os.path.isfile(sheet_path):
        raise FileNotFoundError(f"No annotation sheet at {sheet_path}")
    if not os.path.isfile(key_path):
        raise FileNotFoundError(
            f"No answer key at {key_path}. It is written alongside the sheet by "
            "`python -m evaluation.run annotate`."
        )

    with open(key_path, encoding="utf-8-sig") as handle:
        key = {row["id"]: row for row in csv.DictReader(handle)}

    with open(sheet_path, encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))

    matrix = ConfusionMatrix(labels=LABELS)
    disagreements: list[dict] = []
    skipped = 0

    alignment_correct = alignment_wrong = alignment_unlabelled = 0

    for row in rows:
        human_label = (row.get("annotator_change_type") or "").strip()
        entry = key.get(row["id"])

        if not human_label or entry is None:
            skipped += 1
            continue

        canonical = _canonical_label(human_label)
        if canonical is None:
            raise ValueError(
                f"Row {row['id']}: '{human_label}' is not one of {LABELS}."
            )

        system_label = entry["system_change_type"]
        matrix.add(canonical, system_label)

        if canonical != system_label:
            disagreements.append({
                "id": row["id"],
                "clause_v1": row.get("clause_v1", ""),
                "clause_v2": row.get("clause_v2", ""),
                "annotator": canonical,
                "system": system_label,
                "similarity": entry.get("system_similarity", ""),
                "notes": row.get("annotator_notes", ""),
            })

        alignment_flag = (row.get("annotator_alignment_ok") or "").strip().lower()
        if alignment_flag in {"y", "yes", "true", "1"}:
            alignment_correct += 1
        elif alignment_flag in {"n", "no", "false", "0"}:
            alignment_wrong += 1
        else:
            alignment_unlabelled += 1

    judged = alignment_correct + alignment_wrong

    return AnnotationScore(
        sheet=os.path.basename(sheet_path),
        annotated_rows=matrix.total,
        skipped_rows=skipped,
        change_type=matrix.as_dict(),
        kappa=cohens_kappa(matrix),
        alignment={
            "judged": judged,
            "correct": alignment_correct,
            "wrong": alignment_wrong,
            "unlabelled": alignment_unlabelled,
            "accuracy": round(alignment_correct / judged, 4) if judged else None,
        },
        disagreements=disagreements,
    )


def _canonical_label(value: str) -> Optional[str]:
    folded = value.strip().casefold()
    for label in LABELS:
        if folded == label.casefold():
            return label
    return None
