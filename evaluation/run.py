"""
Evaluation Runner
─────────────────
    python -m evaluation.run accuracy              # E1–E3, writes results/accuracy.json
    python -m evaluation.run annotate --size 150   # blind annotation sheet + key
    python -m evaluation.run score-annotations --sheet <path>
    python -m evaluation.run evolution             # regulation-evolution study
    python -m evaluation.run cross-country         # cross-jurisdiction challenges
    python -m evaluation.run all
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from comparison.engine import SemanticComparator
from config import ALIGNMENT_IDENTIFIER, BASE_DIR
from database.db import init_db
from database.operations import get_clauses
from evaluation import annotation as annotation_module
from evaluation.experiments import (
    find_version,
    run_alignment_recovery,
    run_localisation,
    run_perturbation,
    run_truncation,
    _ref,
)

RESULTS_DIR = os.path.join(BASE_DIR, "evaluation", "results")


def _write(name: str, payload: dict) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    path = os.path.join(RESULTS_DIR, f"{name}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
    return path


def _rule(title: str) -> None:
    print(f"\n{title}")
    print("=" * len(title))


def command_accuracy(args: argparse.Namespace) -> int:
    comparator = SemanticComparator()

    _rule("E1  Change localisation vs the published amendment register")

    # The comparison is the expensive part; compute it once and score it
    # against each candidate register.
    baseline = find_version("Volume 1: Dwellings", "2022 amendments")
    revision = find_version("Volume 1: Dwellings", "2025 amendments")
    shared_report = comparator.compare(
        get_clauses(baseline["id"]), get_clauses(revision["id"]),
        _ref(baseline), _ref(revision),
        strategy=ALIGNMENT_IDENTIFIER,
    )

    # Which amendments does this consolidation actually implement? The title
    # says one thing; scoring against each candidate register shows another.
    candidates = [
        ("2025 only (as incorporated by the title)", ["adb-amd-2025"]),
        ("2024 + 2025", ["adb-amd-2024", "adb-amd-2025"]),
        ("2025 + 2026 + 2029 (as collated by the title)",
         ["adb-amd-2025", "adb-amd-2026", "adb-amd-2029"]),
    ]

    print("  Which register does the consolidation implement?")
    print(f"  {'register':<46}{'amendments':>11}{'found':>7}{'recall':>9}")
    register_scan = []
    for name, booklets in candidates:
        candidate = run_localisation(comparator, booklets=booklets, label=name,
                                     report=shared_report)
        print(f"  {name:<46}{candidate.amendments_scored:>11}"
              f"{candidate.amendments_found:>7}{candidate.amendment_recall:>9.3f}")
        register_scan.append(candidate.as_dict())
    print("  Recall falling as later registers are added is evidence the "
          "consolidation\n  does not contain those amendments.\n")

    localisation = run_localisation(comparator, report=shared_report,
                                    label="2025 only (as incorporated by the title)")
    print(f"  {localisation.baseline}")
    print(f"  → {localisation.revision}")
    print(f"  registers: {', '.join(localisation.booklets)} (volume {localisation.volume})")
    print(f"  clauses named by the regulator : {localisation.gold_clauses}")
    print(f"  of those, present in the corpus: {localisation.gold_matched_in_corpus}")
    print(f"  clauses under comparison       : {localisation.universe}")
    print()
    print(f"  {'min word Δ':>11} {'flagged':>8} {'precision':>10} {'recall':>8} {'F1':>7}")
    for row in localisation.sweep:
        print(
            f"  {row['min_word_change_ratio']:>11.2f} {row['flagged']:>8} "
            f"{row['precision']:>10.3f} {row['recall']:>8.3f} {row['f1']:>7.3f}"
        )

    print(f"\n  amendment-level recall: {localisation.amendments_found}/"
          f"{localisation.amendments_scored} = {localisation.amendment_recall:.3f}")
    not_found = [a["reference"] for a in localisation.amendment_status if not a["found"]]
    print(f"  amendments not surfaced: {not_found or 'none'}")

    if localisation.silent_misses:
        print(f"\n  SILENT MISSES — amended, text differs, classified Unchanged: "
              f"{len(localisation.silent_misses)}")
        for miss in localisation.silent_misses:
            print(f"    {miss['clause']:<16} similarity {miss['similarity']:.4f}  "
                  f"+{miss['words_added']}/-{miss['words_removed']} words")
    else:
        print("\n  silent misses: none")

    unlisted = localisation.unlisted_characterisation
    print(f"\n  differences not in the register: {unlisted['count']}")
    print(f"    edited on both sides    : {unlisted['edited_both_sides']}")
    print(f"      median words changed  : {unlisted['word_change_ratio_of_edited'].get('median')}")
    print(f"      under 2% of words     : {unlisted['edited_under_2_percent_of_words']}  (typesetting)")
    print(f"      over 20% of words     : {unlisted['edited_over_20_percent_of_words']}")
    print(f"    added or removed outright: {unlisted['one_sided_added_or_removed']}  "
          f"(clause-boundary differences)")

    if localisation.unmatched_references:
        print(f"\n  register entries with no matching parsed clause "
              f"({len(localisation.unmatched_references)}): "
              f"{localisation.unmatched_references[:12]}")

    _rule("E2  Semantic alignment recovery vs clause-number ground truth")
    alignment = run_alignment_recovery(comparator)
    print(f"  {alignment.baseline}")
    print(f"  → {alignment.revision}")
    print(f"  pairs by clause number  : {alignment.identifier_pairs}")
    print(f"  pairs by meaning        : {alignment.semantic_pairs}")
    print(f"  correctly recovered     : {alignment.recovered}")
    print(f"  paired with the wrong clause : {alignment.disagreed}")
    print(f"  left unpaired                : {alignment.missed}")
    print(f"  precision={alignment.score['precision']:.3f} "
          f"recall={alignment.score['recall']:.3f} F1={alignment.score['f1']:.3f}")
    print(f"  match score when correct: median {alignment.similarity_of_recovered.get('median')}")
    print(f"  match score when wrong  : median {alignment.similarity_of_disagreed.get('median')}")

    _rule("E3  Controlled perturbation")
    perturbation = run_perturbation(comparator, sample_size=args.sample_size)
    print(f"  sample: {perturbation.sample_size} clauses\n")
    for row in perturbation.by_perturbation:
        print(f"  {row['perturbation']:<20} n={row['pairs']:<4} "
              f"similarity median={row['similarity']['median']:.3f}  "
              f"words changed={row['word_change_ratio']['median']:.3f}")
        print(f"  {'':<20} classified: {row['classified_as']}")
    if perturbation.numeric_finding:
        finding = perturbation.numeric_finding
        print(f"\n  numeric sensitivity: {finding['classified_unchanged_share']:.1%} of clauses "
              f"with a changed measurement were classified Unchanged")
        print(f"  (median similarity {finding['similarity']['median']:.3f} despite "
              f"a real change of dimension)")

    _rule("E3b  Encoder truncation")
    truncation = run_truncation(comparator)
    print(f"  window: {truncation['window_word_pieces']} word pieces "
          f"(~{truncation['window_word_pieces'] * 3 // 4} words)")
    print(f"  clauses longer than the window: {truncation['clauses_exceeding_window']}/"
          f"{truncation['clauses_total']} ({truncation['share_exceeding_window']:.1%})")
    print(f"  test clause is {truncation['base_clause_word_pieces']} word pieces\n")
    print(f"  {'words appended':>15} {'similarity':>12}")
    for point in truncation["append_curve"]:
        print(f"  {point['words_appended']:>15} {point['similarity']:>12.6f}")
    if truncation["blind_to_appended_text"]:
        print("\n  Similarity does not move: text past the window is not read.")
    else:
        print(f"\n  Similarity falls by {truncation['similarity_drop_at_max_append']:.4f} "
              f"across the appended text — the whole clause is read (chunked and pooled).")

    payload = {
        "register_scan": register_scan,
        "truncation": truncation,
        "localisation": localisation.as_dict(),
        "alignment_recovery": alignment.as_dict(),
        "perturbation": perturbation.as_dict(),
    }
    path = _write("accuracy", payload)
    print(f"\nwritten: {os.path.relpath(path, BASE_DIR)}")
    return 0


def command_annotate(args: argparse.Namespace) -> int:
    comparator = SemanticComparator()

    baseline = find_version(args.document, args.baseline)
    revision = find_version(args.document, args.revision)

    print(f"Comparing {baseline['version_label']} → {revision['version_label']} "
          f"to draw the sample…")
    report = comparator.compare(
        get_clauses(baseline["id"]),
        get_clauses(revision["id"]),
        _ref(baseline), _ref(revision),
        strategy=ALIGNMENT_IDENTIFIER,
    )

    sheet, key, protocol = annotation_module.build_sample(
        report, name=args.name, size=args.size
    )

    print(f"\n  sheet    : {os.path.relpath(sheet, BASE_DIR)}   ← label this by hand")
    print(f"  key      : {os.path.relpath(key, BASE_DIR)}   ← do not open until labelling is done")
    print(f"  protocol : {os.path.relpath(protocol, BASE_DIR)}")
    print("\nThe sheet is blind: it holds the clause texts and empty label columns.")
    print("Fill in annotator_change_type and annotator_alignment_ok, then run:")
    print(f"  python -m evaluation.run score-annotations --sheet "
          f"{os.path.relpath(sheet, BASE_DIR)}")
    return 0


def command_score_annotations(args: argparse.Namespace) -> int:
    result = annotation_module.score_annotations(args.sheet, args.key)

    if result.annotated_rows == 0:
        print(f"No labelled rows in {result.sheet}. "
              f"{result.skipped_rows} rows are still blank.")
        return 1

    _rule("E4  System vs manual annotation")
    print(f"  labelled rows : {result.annotated_rows}")
    print(f"  still blank   : {result.skipped_rows}")
    print(f"  accuracy      : {result.change_type['accuracy']:.3f}")
    print(f"  macro F1      : {result.change_type['macro_f1']:.3f}")
    print(f"  Cohen's kappa : {result.kappa:.3f}")
    if result.alignment["accuracy"] is not None:
        print(f"  alignment judged correct: {result.alignment['correct']}/"
              f"{result.alignment['judged']} ({result.alignment['accuracy']:.1%})")

    print("\n  per class:")
    for label, score in result.change_type["per_label"].items():
        if score["true_positives"] + score["false_negatives"] == 0:
            continue
        print(f"    {label:<20} P={score['precision']:.3f} "
              f"R={score['recall']:.3f} F1={score['f1']:.3f}  n={score['true_positives'] + score['false_negatives']}")

    path = _write("annotation", result.as_dict())
    print(f"\nwritten: {os.path.relpath(path, BASE_DIR)}")
    return 0


def command_evolution(args: argparse.Namespace) -> int:
    from evaluation.evolution import run_evolution, render_evolution

    comparator = SemanticComparator()
    result = run_evolution(comparator)
    print(render_evolution(result))
    path = _write("evolution", result)
    print(f"\nwritten: {os.path.relpath(path, BASE_DIR)}")
    return 0


def command_cross_country(args: argparse.Namespace) -> int:
    from evaluation.cross_country import run_cross_country, render_cross_country

    comparator = SemanticComparator()
    result = run_cross_country(comparator)
    print(render_cross_country(result))
    path = _write("cross_country", result)
    print(f"\nwritten: {os.path.relpath(path, BASE_DIR)}")
    return 0


def command_all(args: argparse.Namespace) -> int:
    status = command_accuracy(args)
    status |= command_evolution(args)
    status |= command_cross_country(args)
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the evaluation studies.")
    sub = parser.add_subparsers(dest="command", required=True)

    accuracy = sub.add_parser("accuracy", help="E1-E3: accuracy against external ground truth")
    accuracy.add_argument("--sample-size", type=int, default=120)
    accuracy.set_defaults(handler=command_accuracy)

    annotate = sub.add_parser("annotate", help="write a blind manual-annotation sheet")
    annotate.add_argument("--name", default="adb_v1_2019_vs_2025")
    annotate.add_argument("--size", type=int, default=150)
    annotate.add_argument("--document", default="Volume 1: Dwellings")
    annotate.add_argument("--baseline", default="2019 edition")
    annotate.add_argument("--revision", default="2025 amendments")
    annotate.set_defaults(handler=command_annotate)

    score = sub.add_parser("score-annotations", help="score the system against a completed sheet")
    score.add_argument("--sheet", required=True)
    score.add_argument("--key", default=None)
    score.set_defaults(handler=command_score_annotations)

    evolution = sub.add_parser("evolution", help="patterns in regulation evolution")
    evolution.set_defaults(handler=command_evolution)

    cross = sub.add_parser("cross-country", help="cross-jurisdiction comparison challenges")
    cross.set_defaults(handler=command_cross_country)

    every = sub.add_parser("all", help="run every study that needs no manual input")
    every.add_argument("--sample-size", type=int, default=120)
    every.set_defaults(handler=command_all)

    args = parser.parse_args()
    init_db()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
