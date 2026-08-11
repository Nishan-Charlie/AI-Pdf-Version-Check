"""
Model Diagnostic
────────────────
Checks whether an encoder is properly downloaded and can actually be loaded,
and prints the full reason when it cannot.

Written because a preload failure in the API log is one line, usually cut off
by the terminal. This runs the same steps in the open.

    python scripts/check_model.py              # the configured default
    python scripts/check_model.py bge          # a registry key
    python scripts/check_model.py --fix        # re-download if the copy is bad
    python scripts/check_model.py --all        # every registered model
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
import traceback

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import (
    MODEL_NAME,
    MODEL_REGISTRY,
    hf_repo_id,
    model_is_downloaded,
    resolve_model,
    total_ram_mb,
)

OK = "  ok  "
BAD = " FAIL "
WARN = " warn "


def rule(title: str) -> None:
    print(f"\n{title}")
    print("─" * max(40, len(title)))


def cache_dir(model_id: str) -> str:
    from huggingface_hub.constants import HF_HUB_CACHE

    return os.path.join(
        HF_HUB_CACHE, "models--" + hf_repo_id(model_id).replace("/", "--")
    )


def folder_size_mb(path: str) -> float:
    total = 0
    for root, _, files in os.walk(path):
        for name in files:
            try:
                total += os.stat(os.path.join(root, name), follow_symlinks=False).st_size
            except OSError:
                pass
    return total / 1024 / 1024


def inspect_cache(model_id: str) -> None:
    """What is physically on disk for this model."""
    path = cache_dir(model_id)
    rule("2. What is on disk")
    print(f"  cache folder : {path}")

    if not os.path.isdir(path):
        print(f"{WARN} the folder does not exist — nothing has been downloaded yet")
        return

    print(f"  size         : {folder_size_mb(path):.0f} MB")

    snapshots = os.path.join(path, "snapshots")
    if not os.path.isdir(snapshots):
        print(f"{BAD} no snapshots/ directory — the download did not complete")
        return

    revisions = [r for r in os.listdir(snapshots)
                 if os.path.isdir(os.path.join(snapshots, r))]
    if not revisions:
        print(f"{BAD} snapshots/ is empty — the download did not complete")
        return

    for revision in revisions:
        files = sorted(os.listdir(os.path.join(snapshots, revision)))
        has_config = "config.json" in files
        has_modules = "modules.json" in files
        has_weights = any(f in files for f in ("model.safetensors", "pytorch_model.bin"))
        complete = has_config and has_modules and has_weights

        print(f"\n  snapshot {revision[:12]} — {len(files)} files "
              f"{'(complete)' if complete else '(INCOMPLETE)'}")
        print(f"    config.json   {'yes' if has_config else 'MISSING'}")
        print(f"    modules.json  {'yes' if has_modules else 'MISSING'}")
        print(f"    weights       {'yes' if has_weights else 'MISSING'}")

    # Interrupted transfers leave these behind.
    blobs = os.path.join(path, "blobs")
    if os.path.isdir(blobs):
        partial = [f for f in os.listdir(blobs) if f.endswith(".incomplete")]
        if partial:
            print(f"\n{WARN} {len(partial)} unfinished download(s) in blobs/ — "
                  f"a transfer was interrupted")


def try_load(model_id: str) -> bool:
    """Actually load the model, and show the whole error if it fails."""
    rule("3. Loading it")
    print("  importing sentence-transformers…")

    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} sentence-transformers will not import: {type(exc).__name__}: {exc}")
        print("\n  install the dependencies:  pip install -r requirements.txt")
        return False

    started = time.perf_counter()
    try:
        model = SentenceTransformer(model_id)
    except Exception as exc:  # noqa: BLE001 — showing this is the point
        print(f"{BAD} could not load {model_id}")
        print(f"\n  {type(exc).__name__}: {exc}\n")
        print("  full traceback:")
        traceback.print_exc()
        print(f"\n  most likely: the cached copy is incomplete, or the machine "
              f"cannot reach\n  huggingface.co to finish it. "
              f"Re-run with --fix to delete and download again.")
        return False

    elapsed = time.perf_counter() - started
    print(f"{OK} loaded in {elapsed:.1f}s")
    print(f"  window       : {model.max_seq_length} word pieces")
    print(f"  dimensions   : {model.get_sentence_embedding_dimension()}")

    rule("4. Encoding something")
    try:
        pair = [
            "Every escape route shall be kept clear of obstruction.",
            "Escape routes must remain free from obstruction at all times.",
        ]
        vectors = model.encode(pair, normalize_embeddings=True, show_progress_bar=False)
        similarity = float(vectors[0] @ vectors[1])
        print(f"{OK} encoded 2 clauses, similarity {similarity:.4f}")
        print("  (two ways of saying the same thing should score high)")
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} the model loaded but cannot encode: {type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False

    return True


def repair(model_id: str) -> None:
    """Delete the cached copy so the next load downloads it cleanly."""
    path = cache_dir(model_id)
    rule("Repair")
    if not os.path.isdir(path):
        print("  nothing cached to remove")
        return
    print(f"  removing {path}")
    shutil.rmtree(path, ignore_errors=True)
    print(f"{OK} removed — run this script again to download a fresh copy")


def check(model_key: str, fix: bool) -> bool:
    model_id = resolve_model(model_key)
    entry = next((e for e in MODEL_REGISTRY.values() if e["id"] == model_id), None)

    print("=" * 60)
    print(f"Checking {model_key}  →  {model_id}")
    print("=" * 60)

    rule("1. What is expected")
    if entry:
        print(f"  download     : {entry['size_mb']} MB")
        print(f"  RAM to load  : ~{entry['ram_mb']} MB")
        print(f"  window       : {entry['window']} word pieces")
    else:
        print("  not in the registry — treated as a HuggingFace model id")

    ram = total_ram_mb()
    if ram:
        print(f"  machine RAM  : {ram} MB ({ram / 1024:.1f} GB)")
        if entry and ram and ram < entry["ram_mb"] * 3:
            print(f"{WARN} this model wants ~{entry['ram_mb']} MB; "
                  f"headroom is tight on this machine")

    reported = model_is_downloaded(model_id)
    print(f"  service reports downloaded: {reported}")

    inspect_cache(model_id)

    if fix:
        repair(model_id)

    loaded = try_load(model_id)

    rule("Verdict")
    if loaded:
        print(f"{OK} {model_key} is downloaded and works")
        if not reported:
            print(f"{WARN} but the service's own check said it was NOT downloaded —"
                  f"\n       report this, it is a bug in model_is_downloaded()")
    else:
        print(f"{BAD} {model_key} is not usable on this machine")
        if reported:
            print(f"{WARN} the service believed it was downloaded, which is why the"
                  f"\n       preload failed instead of fetching it")
    return loaded


def main() -> int:
    parser = argparse.ArgumentParser(description="Check that a model downloads and loads.")
    parser.add_argument("model", nargs="?", default=None,
                        help="registry key or model id (default: the configured model)")
    parser.add_argument("--fix", action="store_true",
                        help="delete the cached copy first, forcing a clean download")
    parser.add_argument("--all", action="store_true",
                        help="check every registered model")
    args = parser.parse_args()

    if args.all:
        results = {key: check(key, args.fix) for key in MODEL_REGISTRY}
        rule("Summary")
        for key, ok in results.items():
            print(f"  {key:<8} {'ok' if ok else 'FAILED'}")
        return 0 if all(results.values()) else 1

    target = args.model or next(
        (k for k, e in MODEL_REGISTRY.items() if e["id"] == MODEL_NAME), MODEL_NAME
    )
    return 0 if check(target, args.fix) else 1


if __name__ == "__main__":
    raise SystemExit(main())
