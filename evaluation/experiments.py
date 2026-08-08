"""
Accuracy Experiments
────────────────────
Three studies, each measuring something the others cannot.

E1  Change localisation against the published amendment register.
    Does the system flag the clauses MHCLG says it changed?

E2  Semantic alignment recovery.
    Within one instrument, clause numbers give a correct pairing for free.
    Hiding them and asking the semantic matcher to rebuild that pairing
    measures the matcher that cross-country comparison depends on, on a case
    where the right answer is known.

E3  Controlled perturbation.
    Real clauses edited in known ways, to characterise what the similarity
    score is and is not sensitive to.

E1 and E2 have external ground truth. E3 is a behavioural study: its
"expected" labels encode the thresholds' design intent, so it reports whether
the system behaves as specified, not whether the specification is right.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Optional

from comparison.alignment import align_by_identifier, align_semantic
from comparison.diff import redline
from comparison.engine import SemanticComparator
from comparison.report import ChangeType, VersionRef
from config import ALIGNMENT_IDENTIFIER, ALIGNMENT_SEMANTIC
from database.operations import get_clauses, list_all_versions
from evaluation.amendment_key import changed_references
from evaluation.metrics import ConfusionMatrix, describe, score_sets

CHANGED_TYPES = {
    ChangeType.MINOR_EDIT,
    ChangeType.SIGNIFICANT_CHANGE,
    ChangeType.ADDED,
    ChangeType.REMOVED,
}


# ── Version lookup ───────────────────────────────────────────────────

def find_version(document_contains: str, version_label: str) -> dict:
    """Locate a stored version by a fragment of its document name and its label."""
    for version in list_all_versions():
        if document_contains in version["document_name"] and version["version_label"] == version_label:
            return version
    raise LookupError(
        f"No stored version matching '{document_contains}' / '{version_label}'. "
        "Run `python -m corpus.load` first."
    )


def _ref(version: dict) -> VersionRef:
    return VersionRef(
        version_id=version["id"],
        document_name=version["document_name"],
        version_label=version["version_label"],
        country_code=version["country_code"],
        country_name=version["country_name"],
    )


# ── E1: change localisation ──────────────────────────────────────────

@dataclass
class LocalisationResult:
    label: str
    baseline: str
    revision: str
    booklets: list[str]
    volume: int
    gold_clauses: int
    gold_matched_in_corpus: int
    universe: int
    sweep: list[dict]
    best_recall: dict
    unmatched_references: list[str]
    missed_references: list[str]
    unlisted_characterisation: dict
    amendment_recall: float
    amendments_scored: int
    amendments_found: int
    amendment_status: list[dict]
    silent_misses: list[dict]

    def as_dict(self) -> dict:
        return {
            "experiment": "E1 change localisation vs published amendment register",
            "register": self.label,
            "baseline": self.baseline,
            "revision": self.revision,
            "booklets": self.booklets,
            "volume": self.volume,
            "gold_clauses_named": self.gold_clauses,
            "gold_present_in_corpus": self.gold_matched_in_corpus,
            "clauses_under_comparison": self.universe,
            "amendment_recall": round(self.amendment_recall, 4),
            "amendments_scored": self.amendments_scored,
            "amendments_found": self.amendments_found,
            "amendment_status": self.amendment_status,
            "silent_misses": self.silent_misses,
            "sweep": self.sweep,
            "best_recall": self.best_recall,
            "references_absent_from_corpus": self.unmatched_references,
            "amendments_the_system_missed": self.missed_references,
            "unlisted_differences": self.unlisted_characterisation,
            "how_to_read": (
                "`amendment_recall` is the headline accuracy figure: the share "
                "of published amendments the auditor is pointed at. `sweep` "
                "recall is stricter — it requires every clause an instruction "
                "covers to be flagged, including paragraphs a section-wide "
                "replacement left identical. Precision is not an error rate: "
                "the register lists substantive amendments, while the system "
                "reports every textual difference between two separately "
                "typeset PDFs, so it measures review burden. `silent_misses` "
                "is the failure that matters — clauses the regulator amended, "
                "whose text does differ, that the similarity threshold "
                "classified Unchanged."
            ),
        }


def run_localisation(
    comparator: SemanticComparator,
    document: str = "Volume 1: Dwellings",
    baseline_label: str = "2022 amendments",
    revision_label: str = "2025 amendments",
    booklets: Optional[list[str]] = None,
    volume: int = 1,
    label: str = "",
    report=None,
) -> LocalisationResult:
    """
    Score change detection against the regulator's own list of amendments.

    The reference standard is the 2025 register alone. The revision under test
    is titled as being collated with the 2026 and 2029 amendments, but it does
    not incorporate them: clauses those later registers name — 3.7 and 3.33
    among them — are byte-identical to the 2022 text. Scoring against all three
    registers would therefore penalise the system for failing to find changes
    that are not in the document.

    Precision is expected to be low and that is a measurement, not a fault:
    the register lists substantive amendments, while re-typesetting a PDF
    changes hyphenation, spacing, and line breaks throughout. Sweeping a
    minimum word-change ratio shows how far that noise can be filtered before
    real amendments start being lost.
    """
    booklets = booklets or ["adb-amd-2025"]

    baseline = find_version(document, baseline_label)
    revision = find_version(document, revision_label)

    if report is None:
        report = comparator.compare(
            get_clauses(baseline["id"]), get_clauses(revision["id"]),
            _ref(baseline), _ref(revision),
            strategy=ALIGNMENT_IDENTIFIER,
        )

    _, amendments = changed_references(booklets, volume=volume)

    # The universe is every clause the comparison actually covers.
    universe = {
        row.v1.clause_number if row.v1 else row.v2.clause_number
        for row in report.comparisons
    }

    # A clause is in the reference standard if any amendment reaches it —
    # directly, or by naming the section or appendix that contains it.
    gold = {
        number for number in universe
        if any(amendment.covers(number) for amendment in amendments)
    }

    # References the corpus has no clause for — a parser coverage measurement,
    # reported rather than quietly dropped.
    unmatched = sorted({
        a.reference for a in amendments
        if not any(a.covers(number) for number in universe)
    })

    sweep: list[dict] = []
    predicted_at_zero: set[str] = set()

    for threshold in (0.0, 0.01, 0.02, 0.05, 0.10, 0.20, 0.30, 0.50):
        predicted = set()
        for row in report.comparisons:
            if row.change_type not in CHANGED_TYPES:
                continue
            if row.redline.get("word_change_ratio", 0.0) < threshold:
                continue
            number = row.v1.clause_number if row.v1 else row.v2.clause_number
            predicted.add(number)

        predicted &= universe
        if threshold == 0.0:
            predicted_at_zero = predicted

        score = score_sets(predicted, gold, universe)
        sweep.append({
            "min_word_change_ratio": threshold,
            "flagged": len(predicted),
            **score.as_dict(),
        })

    # The operating point that keeps every published amendment while flagging
    # as little else as possible.
    full_recall = [row for row in sweep if row["recall"] >= 1.0]
    best_recall = min(full_recall, key=lambda row: row["flagged"]) if full_recall else max(
        sweep, key=lambda row: row["recall"]
    )

    missed = sorted(gold - predicted_at_zero)

    # Recall at the granularity the regulator actually amends at. A single
    # instruction can replace a whole section, and it is satisfied once the
    # auditor is pointed at any changed clause inside it — requiring every
    # clause in the section to differ would count unchanged paragraphs of a
    # replaced section as failures.
    amendment_status: list[dict] = []
    for amendment in amendments:
        covered = {number for number in universe if amendment.covers(number)}
        if not covered:
            continue  # not represented in the parsed corpus; counted separately
        amendment_status.append({
            "reference": amendment.reference,
            "operation": amendment.operation,
            "clauses_in_corpus": len(covered),
            "found": bool(covered & predicted_at_zero),
        })

    found_count = sum(1 for a in amendment_status if a["found"])
    amendment_recall = found_count / len(amendment_status) if amendment_status else 0.0

    # The failure that matters: a clause the regulator amended, whose text
    # genuinely differs, that the similarity threshold called Unchanged. These
    # are invisible to an auditor using the tool.
    silent_misses = []
    for row in report.comparisons:
        if not (row.v1 and row.v2):
            continue
        number = row.v1.clause_number
        if number not in gold or row.change_type != ChangeType.UNCHANGED:
            continue
        if row.v1.content == row.v2.content:
            continue  # correctly unchanged
        silent_misses.append({
            "clause": number,
            "similarity": row.similarity_score,
            "word_change_ratio": row.redline.get("word_change_ratio"),
            "words_added": row.redline.get("words_added"),
            "words_removed": row.redline.get("words_removed"),
        })

    # What are the flags the register does not list?
    #
    # Added and Removed rows are separated out: their word-change ratio is 1.0
    # by definition, since one side has no text, so pooling them with edited
    # clauses would make the whole set look like wholesale rewriting. They are
    # mostly clause-boundary differences between two parses, not amendments.
    unlisted = [
        row for row in report.comparisons
        if row.change_type in CHANGED_TYPES
        and (row.v1.clause_number if row.v1 else row.v2.clause_number) in (predicted_at_zero - gold)
    ]
    edited = [r for r in unlisted if r.change_type in
              (ChangeType.MINOR_EDIT, ChangeType.SIGNIFICANT_CHANGE)]
    one_sided = [r for r in unlisted if r.change_type in
                 (ChangeType.ADDED, ChangeType.REMOVED)]
    ratios = [row.redline.get("word_change_ratio", 0.0) for row in edited]

    return LocalisationResult(
        label=label or "+".join(b.replace("adb-amd-", "") for b in booklets),
        baseline=f"{baseline['document_name']} — {baseline_label}",
        revision=f"{revision['document_name']} — {revision_label}",
        booklets=booklets,
        volume=volume,
        gold_clauses=len({a.reference for a in amendments}),
        gold_matched_in_corpus=len(gold),
        universe=len(universe),
        sweep=sweep,
        best_recall=best_recall,
        unmatched_references=unmatched,
        missed_references=missed,
        amendment_recall=amendment_recall,
        amendments_scored=len(amendment_status),
        amendments_found=found_count,
        amendment_status=amendment_status,
        silent_misses=silent_misses,
        unlisted_characterisation={
            "count": len(unlisted),
            "edited_both_sides": len(edited),
            "one_sided_added_or_removed": len(one_sided),
            "word_change_ratio_of_edited": describe(ratios),
            "edited_under_2_percent_of_words": sum(1 for r in ratios if r < 0.02),
            "edited_over_20_percent_of_words": sum(1 for r in ratios if r >= 0.20),
            "reading": (
                "One-sided rows have a word-change ratio of 1.0 by construction "
                "and are counted separately; they mostly reflect clause-boundary "
                "differences between two parses rather than amendments."
            ),
        },
    )


# ── E2: semantic alignment recovery ──────────────────────────────────

@dataclass
class AlignmentResult:
    baseline: str
    revision: str
    identifier_pairs: int
    semantic_pairs: int
    recovered: int
    disagreed: int
    missed: int
    score: dict
    similarity_of_recovered: dict
    similarity_of_disagreed: dict

    def as_dict(self) -> dict:
        return {
            "experiment": "E2 semantic alignment recovery vs clause-number ground truth",
            "baseline": self.baseline,
            "revision": self.revision,
            "identifier_pairs": self.identifier_pairs,
            "semantic_pairs": self.semantic_pairs,
            "recovered": self.recovered,
            "disagreed": self.disagreed,
            "missed": self.missed,
            "score": self.score,
            "match_score_when_correct": self.similarity_of_recovered,
            "match_score_when_wrong": self.similarity_of_disagreed,
        }


def run_alignment_recovery(
    comparator: SemanticComparator,
    document: str = "Volume 1: Dwellings",
    baseline_label: str = "2019 edition",
    revision_label: str = "2025 amendments",
) -> AlignmentResult:
    """
    Measure the semantic matcher against a pairing that is known to be right.

    Two editions of one instrument share a numbering scheme, so pairing on
    clause number is correct by construction. Running semantic alignment over
    the same two documents — which never looks at the numbers — and asking how
    much of that pairing it rebuilds gives a direct accuracy figure for the
    mechanism cross-country comparison relies on, without needing anybody to
    annotate anything.
    """
    baseline = find_version(document, baseline_label)
    revision = find_version(document, revision_label)

    clauses_v1 = get_clauses(baseline["id"])
    clauses_v2 = get_clauses(revision["id"])

    identifier_pairs = {
        (pair.index_v1, pair.index_v2)
        for pair in align_by_identifier(clauses_v1, clauses_v2)
        if pair.is_pair
    }

    semantic = align_semantic(clauses_v1, clauses_v2, comparator.encode)
    semantic_pairs = {(p.index_v1, p.index_v2) for p in semantic if p.is_pair}

    score = score_sets(semantic_pairs, identifier_pairs)

    # Where clause numbers say a clause has a counterpart, did the semantic
    # matcher pair it with something else, or fail to pair it at all?
    truth_left = {i for i, _ in identifier_pairs}
    semantic_left = {i for i, _ in semantic_pairs}

    disagreed = len({
        i for i in truth_left & semantic_left
        if (i, dict(semantic_pairs)[i]) not in identifier_pairs
    })
    missed = len(truth_left - semantic_left)

    correct_scores = [
        p.match_score for p in semantic
        if p.is_pair and (p.index_v1, p.index_v2) in identifier_pairs
        and p.match_score is not None
    ]
    wrong_scores = [
        p.match_score for p in semantic
        if p.is_pair and (p.index_v1, p.index_v2) not in identifier_pairs
        and p.match_score is not None
    ]

    return AlignmentResult(
        baseline=f"{baseline['document_name']} — {baseline_label}",
        revision=f"{revision['document_name']} — {revision_label}",
        identifier_pairs=len(identifier_pairs),
        semantic_pairs=len(semantic_pairs),
        recovered=score.true_positives,
        disagreed=disagreed,
        missed=missed,
        score=score.as_dict(),
        similarity_of_recovered=describe(correct_scores),
        similarity_of_disagreed=describe(wrong_scores),
    )


# ── E3: controlled perturbation ──────────────────────────────────────

_NUMBER = re.compile(r"\b(\d+(?:\.\d+)?)\s*(mm|m|metres|minutes|min|%)\b", re.IGNORECASE)
_SENTENCE = re.compile(r"(?<=[.;])\s+")


@dataclass
class PerturbationResult:
    sample_size: int
    by_perturbation: list[dict]
    matrix: dict
    numeric_finding: dict

    def as_dict(self) -> dict:
        return {
            "experiment": "E3 controlled perturbation (behavioural characterisation)",
            "sample_size": self.sample_size,
            "by_perturbation": self.by_perturbation,
            "confusion": self.matrix,
            "numeric_sensitivity": self.numeric_finding,
        }


def _perturb_numbers(text: str) -> Optional[str]:
    """Change every measurement in the clause — the edit fire safety cares about."""
    if not _NUMBER.search(text):
        return None

    def bump(match: re.Match) -> str:
        value = float(match.group(1))
        changed = value * 1.25 if value else 1.0
        rendered = f"{changed:.0f}" if changed >= 10 else f"{changed:.1f}"
        return f"{rendered}{match.group(0)[len(match.group(1)):]}"

    altered = _NUMBER.sub(bump, text)
    return altered if altered != text else None


def _drop_last_sentence(text: str) -> Optional[str]:
    sentences = _SENTENCE.split(text)
    if len(sentences) < 3:
        return None
    return " ".join(sentences[:-1])


def _reorder_clauses(text: str) -> Optional[str]:
    """Reorder sentences: same requirements, different presentation."""
    sentences = _SENTENCE.split(text)
    if len(sentences) < 3:
        return None
    return " ".join([sentences[-1]] + sentences[1:-1] + [sentences[0]])


PERTURBATIONS = [
    # name, function, expected classification, whether truth is unambiguous
    ("identity", lambda t: t, ChangeType.UNCHANGED, True),
    ("numeric_values", _perturb_numbers, None, False),
    ("sentence_removed", _drop_last_sentence, None, False),
    ("sentence_reordered", _reorder_clauses, ChangeType.UNCHANGED, False),
]


def run_perturbation(
    comparator: SemanticComparator,
    document: str = "Volume 1: Dwellings",
    version_label: str = "2025 amendments",
    sample_size: int = 120,
    seed: int = 20260808,
) -> PerturbationResult:
    """
    Characterise what the similarity score responds to.

    The headline measurement is numeric sensitivity: in fire safety a changed
    measurement is often the entire substance of an amendment, and a sentence
    encoder trained on general text has little reason to distinguish 600mm
    from 750mm. Quantifying that gap is the point.

    Classification here is called on the similarity alone, without the redline,
    deliberately: the word-evidence guard in `SemanticComparator.classify`
    would mask exactly the encoder behaviour this experiment exists to measure.
    These figures describe the embedding, not the shipped pipeline.
    """
    version = find_version(document, version_label)
    clauses = [c for c in get_clauses(version["id"]) if len(c["content"]) >= 200]

    rng = random.Random(seed)
    rng.shuffle(clauses)
    sample = clauses[:sample_size]

    labels = [t.value for t in ChangeType]
    matrix = ConfusionMatrix(labels=labels)

    rows: list[dict] = []
    numeric_similarities: list[float] = []
    numeric_word_ratios: list[float] = []

    for name, perturb, expected, unambiguous in PERTURBATIONS:
        pairs: list[tuple[str, str]] = []
        for clause in sample:
            original = clause["content"]
            altered = perturb(original)
            if altered is None or altered == original and name != "identity":
                continue
            pairs.append((original, altered))

        if not pairs:
            continue

        texts = [text for pair in pairs for text in pair]
        embeddings = comparator.encode(texts)

        similarities: list[float] = []
        word_ratios: list[float] = []
        observed: list[str] = []

        for index, (original, altered) in enumerate(pairs):
            similarity = float(embeddings[2 * index] @ embeddings[2 * index + 1])
            similarities.append(similarity)

            marks = redline(original, altered)
            word_ratios.append(marks.word_change_ratio)

            classification = comparator.classify(similarity)
            observed.append(classification.value)

            if expected is not None:
                matrix.add(expected.value, classification.value)

        distribution = {label: observed.count(label) for label in labels if observed.count(label)}

        rows.append({
            "perturbation": name,
            "pairs": len(pairs),
            "expected": expected.value if expected else "not specified",
            "truth_unambiguous": unambiguous,
            "similarity": describe(similarities),
            "word_change_ratio": describe(word_ratios),
            "classified_as": distribution,
        })

        if name == "numeric_values":
            numeric_similarities = similarities
            numeric_word_ratios = word_ratios

    numeric_finding = {}
    if numeric_similarities:
        unchanged_share = sum(
            1 for s in numeric_similarities
            if comparator.classify(s) == ChangeType.UNCHANGED
        ) / len(numeric_similarities)

        numeric_finding = {
            "pairs": len(numeric_similarities),
            "similarity": describe(numeric_similarities),
            "word_change_ratio": describe(numeric_word_ratios),
            "classified_unchanged_share": round(unchanged_share, 4),
            "reading": (
                "Every one of these pairs differs in at least one measurement. "
                "The share classified Unchanged is the rate at which a "
                "similarity-only pipeline would hide a changed dimension."
            ),
        }

    return PerturbationResult(
        sample_size=len(sample),
        by_perturbation=rows,
        matrix=matrix.as_dict(),
        numeric_finding=numeric_finding,
    )


# ── E3b: truncation blindness ────────────────────────────────────────

def run_truncation(
    comparator: SemanticComparator,
    document: str = "Volume 1: Dwellings",
    version_label: str = "2025 amendments",
) -> dict:
    """
    Measure how much of a clause the encoder actually reads.

    Sentence-Transformer models take a fixed number of word pieces and discard
    the rest. Two clauses that share an opening therefore embed identically
    however far they diverge afterwards. Regulation clauses routinely exceed
    that window, so this is not a corner case: it is a blind spot covering a
    measurable share of the corpus.

    The experiment appends increasing amounts of unrelated regulatory text to
    a long clause and records the similarity, which should fall and does not.
    """
    window = comparator.model.max_seq_length
    tokenizer = comparator.model.tokenizer

    version = find_version(document, version_label)
    clauses = get_clauses(version["id"])

    # How much of the whole library is longer than the encoder can read?
    exposed = total = 0
    for stored in list_all_versions():
        for clause in get_clauses(stored["id"]):
            total += 1
            if len(tokenizer.tokenize(clause["content"])) > window:
                exposed += 1

    base = max(clauses, key=lambda c: len(c["content"]))["content"]
    filler = (
        " The fire and rescue service shall be provided with vehicle access "
        "to the perimeter of the building at all times."
    )

    curve = []
    for repeats in (0, 1, 2, 5, 10, 20, 40):
        altered = base + filler * repeats
        curve.append({
            "words_appended": len(altered.split()) - len(base.split()),
            "similarity": round(comparator.compare_texts(base, altered), 6),
        })

    return {
        "experiment": "E3b encoder truncation",
        "model": comparator._model_name,
        "window_word_pieces": window,
        "base_clause_word_pieces": len(tokenizer.tokenize(base)),
        "clauses_exceeding_window": exposed,
        "clauses_total": total,
        "share_exceeding_window": round(exposed / total, 4) if total else 0.0,
        "append_curve": curve,
        "reading": (
            "Similarity does not move as text is appended past the window. "
            "Any amendment beyond the first ~180 words of a clause is invisible "
            "to the embedding. The word-level redline is not truncated and does "
            "count those words, which is why classification takes the redline "
            "into account (see MAX_UNCHANGED_WORD_* in config)."
        ),
    }
