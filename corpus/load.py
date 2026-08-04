"""
Corpus Loader
─────────────
Puts the collected reference standards into the database as documents and
versions, so a fresh checkout has something real to compare.

Versions of one instrument are grouped under one document name, which is what
lets the dashboard offer "2019 edition vs 2025 amendments" out of the box. The
groupings are declared here rather than guessed from filenames.

    python -m corpus.load              # load everything already downloaded
    python -m corpus.load --only SC IE
    python -m corpus.load --replace    # re-parse and overwrite existing versions
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import CORPUS_TEXT_DIR
from corpus.registry import ENTRIES, CorpusEntry
from database.db import init_db
from database.operations import add_version, list_all_versions, upsert_document
from ingestion.pipeline import ingest_text

# corpus key → (document it belongs to, label for this edition)
LOAD_PLAN: dict[str, tuple[str, str]] = {
    "adb-2019-v1": ("Approved Document B — Volume 1: Dwellings", "2019 edition"),
    "adb-2022-v1": ("Approved Document B — Volume 1: Dwellings", "2022 amendments"),
    "adb-2025-v1": ("Approved Document B — Volume 1: Dwellings", "2025 amendments"),
    "adb-2022-v2": ("Approved Document B — Volume 2: Other buildings", "2022 amendments"),
    "adb-2025-v2": ("Approved Document B — Volume 2: Other buildings", "2025 amendments"),

    "adb-amd-2020": ("Approved Document B — Amendment booklets", "May 2020"),
    "adb-amd-2022": ("Approved Document B — Amendment booklets", "June 2022"),
    "adb-amd-2024": ("Approved Document B — Amendment booklets", "March 2024"),
    "adb-amd-2025": ("Approved Document B — Amendment booklets", "2025"),
    "adb-amd-2026": ("Approved Document B — Amendment booklets", "2026"),
    "adb-amd-2029": ("Approved Document B — Amendment booklets", "2029"),

    "ni-tbe-2012": ("Technical Booklet E — Fire safety", "October 2012"),

    "ie-tgdb-2020-amended": ("Technical Guidance Document B — Fire Safety", "2006 ed. amended 2020"),
    "ie-tgdb-2024-v1": ("Technical Guidance Document B — Volume 1", "2024 edition"),
    "ie-tgdb-2020-v2": ("Technical Guidance Document B — Volume 2: Dwelling houses", "2020 reprint"),

    "sc-thb-2022-nd": ("Building Standards Technical Handbook — Non-domestic", "2022 edition"),
    "sc-thb-2022-d": ("Building Standards Technical Handbook — Domestic", "2022 edition"),
}


def _text_path(entry: CorpusEntry) -> str:
    return os.path.join(CORPUS_TEXT_DIR, f"{entry.key}.txt")


def load_entry(entry: CorpusEntry, existing: set[tuple[str, str]], replace: bool) -> str:
    """Parse one corpus file into the database. Returns a status line."""
    plan = LOAD_PLAN.get(entry.key)
    if plan is None:
        return "skipped — not in the load plan"

    document_name, version_label = plan

    if (document_name, version_label) in existing and not replace:
        return f"already loaded as {version_label}"

    path = _text_path(entry)
    if not os.path.isfile(path):
        return "skipped — no extracted text (run `python -m corpus.fetch --extract`)"

    with open(path, encoding="utf-8") as handle:
        text = handle.read()

    # The jurisdiction is known from the registry, so the parser is told which
    # grammar to use rather than inferring it.
    result = ingest_text(text, country_code=entry.jurisdiction, pre_cleaned=False)

    if not result.clauses:
        return "FAILED — no clauses parsed"

    document = upsert_document(
        name=document_name,
        description=entry.title,
        country_code=entry.jurisdiction,
        doc_type=result.profile_label,
        publisher=entry.publisher,
    )
    add_version(
        document_id=document["id"],
        version_label=version_label,
        source_file=entry.filename,
        clauses_data=result.clauses,
        parser_profile=result.profile_name,
        parser_confidence=f"{result.confidence:.2f}",
    )

    return f"{len(result.clauses):>5} clauses → {document_name} / {version_label}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Load the reference corpus into the database.")
    parser.add_argument("--only", nargs="*", metavar="CODE", help="limit to jurisdiction codes")
    parser.add_argument("--replace", action="store_true", help="re-parse versions already loaded")
    args = parser.parse_args()

    init_db()

    existing = {
        (v["document_name"], v["version_label"]) for v in list_all_versions()
    }

    targets = [e for e in ENTRIES if e.key in LOAD_PLAN]
    if args.only:
        wanted = {code.upper() for code in args.only}
        targets = [e for e in targets if e.jurisdiction in wanted]

    failures = 0
    for entry in targets:
        message = load_entry(entry, existing, args.replace)
        print(f"{entry.key:<24} {message}")
        if message.startswith("FAILED"):
            failures += 1

    print()
    for version in list_all_versions():
        print(
            f"  {version['country_code']:<4} {version['document_name'][:52]:<54}"
            f" {version['version_label']:<24} {version['clause_count']:>6} clauses"
        )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
