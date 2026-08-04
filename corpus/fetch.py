"""
Corpus Fetcher
──────────────
Downloads the openly-published standards in `registry.py` into corpus/raw/,
then runs each one through the PyMuPDF extractor to produce the plain-text
corpus in corpus/text/.

    python -m corpus.fetch                 # download everything missing
    python -m corpus.fetch --extract       # download, then extract text
    python -m corpus.fetch --only EW SC    # limit to jurisdictions
    python -m corpus.fetch --status        # print the checklist, download nothing
"""

from __future__ import annotations

import argparse
import os
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# The checklist prints box-drawing rules; the default Windows console codepage
# cannot encode them.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import CORPUS_RAW_DIR, CORPUS_TEXT_DIR, jurisdiction_name
from corpus.registry import ENTRIES, CorpusEntry, open_entries, summary

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FireSafetyCorpusFetcher/1.0 "
    "(+research use; contact your institution)"
)
_TIMEOUT = 180


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def download(entry: CorpusEntry, force: bool = False) -> tuple[bool, str]:
    """
    Fetch one entry. Returns (ok, message).

    Existing files are left alone unless `force` is set, so re-running the
    fetcher is cheap and safe.
    """
    if entry.access != "open":
        return False, "licensed — download it from the publisher yourself"

    if entry.present and not force:
        return True, f"already held ({_human(entry.size_bytes)})"

    os.makedirs(CORPUS_RAW_DIR, exist_ok=True)
    request = urllib.request.Request(entry.url, headers={"User-Agent": _USER_AGENT})
    tmp_path = entry.path + ".part"

    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            payload = response.read()
    except (urllib.error.URLError, urllib.error.HTTPError, ssl.SSLError, TimeoutError) as exc:
        return False, f"download failed: {exc}"

    if not payload.startswith(b"%PDF"):
        # A login wall or a 404 page rendered as HTML — do not keep it.
        hint = content_type or "unknown content type"
        return False, f"server returned {hint}, not a PDF"

    with open(tmp_path, "wb") as handle:
        handle.write(payload)
    os.replace(tmp_path, entry.path)

    return True, f"downloaded {_human(len(payload))}"


def extract(entry: CorpusEntry, force: bool = False) -> tuple[bool, str]:
    """Run a held PDF through the extractor and write corpus/text/<key>.txt."""
    if not entry.present:
        return False, "no PDF held"

    from ingestion.extractor import extract_text_from_pdf

    os.makedirs(CORPUS_TEXT_DIR, exist_ok=True)
    out_path = os.path.join(CORPUS_TEXT_DIR, f"{entry.key}.txt")

    if os.path.isfile(out_path) and not force:
        return True, "text already extracted"

    try:
        text = extract_text_from_pdf(entry.path)
    except Exception as exc:  # noqa: BLE001 — report, don't abort the batch
        return False, f"extraction failed: {exc}"

    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write(text)

    return True, f"extracted {len(text):,} chars"


def print_checklist() -> None:
    """Print the collection checklist grouped by jurisdiction."""
    by_jurisdiction: dict[str, list[CorpusEntry]] = {}
    for entry in ENTRIES:
        by_jurisdiction.setdefault(entry.jurisdiction, []).append(entry)

    for code, entries in by_jurisdiction.items():
        print(f"\n{jurisdiction_name(code)}")
        print("─" * 72)
        for entry in entries:
            if entry.present:
                mark = "[x]"
                detail = _human(entry.size_bytes)
            elif entry.access == "licensed":
                mark = "[$]"
                detail = "licensed — supply your own copy"
            else:
                mark = "[ ]"
                detail = "not collected"
            print(f"  {mark} {entry.title}")
            print(f"      {entry.edition} · {detail}")

    stats = summary()
    print(
        f"\n{stats['downloadable_collected']}/{stats['downloadable']} open documents held"
        f" · {stats['licensed_collected']}/{stats['licensed']} licensed documents supplied"
        f" · {_human(stats['bytes'])} on disk"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch the fire safety reference corpus.")
    parser.add_argument("--status", action="store_true", help="print the checklist and exit")
    parser.add_argument("--extract", action="store_true", help="extract text after downloading")
    parser.add_argument("--force", action="store_true", help="re-download files already held")
    parser.add_argument("--only", nargs="*", metavar="CODE", help="limit to jurisdiction codes")
    args = parser.parse_args()

    if args.status:
        print_checklist()
        return 0

    targets = open_entries()
    if args.only:
        wanted = {code.upper() for code in args.only}
        targets = [e for e in targets if e.jurisdiction in wanted]

    failures = 0
    for entry in targets:
        ok, message = download(entry, force=args.force)
        print(f"{'ok  ' if ok else 'FAIL'} {entry.key:<24} {message}")
        if not ok:
            failures += 1
            continue
        if args.extract:
            ok, message = extract(entry, force=args.force)
            print(f"{'  ->' if ok else 'FAIL'} {entry.key:<24} {message}")
            if not ok:
                failures += 1

    print()
    print_checklist()
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
