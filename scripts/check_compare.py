"""
Comparison Diagnostic
─────────────────────
Finds out where a comparison actually fails, by running it at three levels and
reporting memory as it goes:

    1. in this process, with no server at all
    2. against the API directly
    3. against the API through the dashboard's proxy

The first that fails is the layer at fault. If level 1 fails the comparison
itself is the problem; if only level 3 fails, the dashboard's proxy is.

    python scripts/check_compare.py
    python scripts/check_compare.py --model bge
    python scripts/check_compare.py --small     # two tiny documents
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config import resolve_model, total_ram_mb

API = "http://127.0.0.1:8000"
WEB = "http://localhost:3000"

OK, BAD, SKIP = "  ok  ", " FAIL ", " skip "


def rss_mb() -> float:
    """Resident memory of this process, best effort, without new dependencies."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [
                    ("cb", wintypes.DWORD),
                    ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t),
                    ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t),
                    ("PeakPagefileUsage", ctypes.c_size_t),
                ]

            kernel32 = ctypes.windll.kernel32
            # Without this the handle is truncated to 32 bits on a 64-bit
            # build and the call silently returns zero.
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE

            query = ctypes.windll.psapi.GetProcessMemoryInfo
            query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            query.restype = wintypes.BOOL

            counters = Counters()
            counters.cb = ctypes.sizeof(Counters)
            if not query(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
                return 0.0
            return counters.WorkingSetSize / 1024 / 1024
        except Exception:  # noqa: BLE001
            return 0.0

    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Linux reports kilobytes, macOS bytes.
        return peak / 1024 if sys.platform.startswith("linux") else peak / 1024 / 1024
    except Exception:  # noqa: BLE001
        return 0.0


def note(label: str) -> None:
    memory = rss_mb()
    print(f"      {label:<34}{memory:>8.0f} MB" if memory else f"      {label}")


def rule(title: str) -> None:
    print(f"\n{title}")
    print("─" * max(46, len(title)))


def pick_versions(small: bool) -> tuple[dict, dict]:
    """Two stored editions to compare."""
    from database.operations import list_all_versions

    versions = list_all_versions()
    if len(versions) < 2:
        raise SystemExit("Fewer than two editions are stored. Run `python -m corpus.load`.")

    by = {(v["document_name"], v["version_label"]): v for v in versions}

    if small:
        booklets = [v for v in versions if "Amendment booklets" in v["document_name"]]
        if len(booklets) >= 2:
            ordered = sorted(booklets, key=lambda v: v["clause_count"])
            return ordered[0], ordered[1]

    preferred = [
        ("Approved Document B — Volume 1: Dwellings", "2019 edition"),
        ("Approved Document B — Volume 1: Dwellings", "2025 amendments"),
    ]
    if all(p in by for p in preferred):
        return by[preferred[0]], by[preferred[1]]

    ordered = sorted(versions, key=lambda v: -v["clause_count"])
    return ordered[1], ordered[0]


def level_one(baseline: dict, revision: dict, model: str) -> bool:
    """Run the comparison in this process. No server involved."""
    rule("1. In this process (no server)")
    print(f"  {baseline['version_label']} → {revision['version_label']}  "
          f"({baseline['clause_count']} vs {revision['clause_count']} clauses)")
    note("before loading anything")

    try:
        from comparison.engine import get_comparator
        from comparison.report import VersionRef
        from database.operations import get_clauses

        started = time.perf_counter()
        comparator = get_comparator(model)
        note("model loaded")

        clauses_v1 = get_clauses(baseline["id"])
        clauses_v2 = get_clauses(revision["id"])
        note("clauses read from the database")

        def ref(v: dict) -> VersionRef:
            return VersionRef(v["id"], v["document_name"], v["version_label"],
                              v["country_code"], v["country_name"])

        report = comparator.compare(clauses_v1, clauses_v2, ref(baseline), ref(revision))
        note("comparison finished")

        elapsed = time.perf_counter() - started
        print(f"{OK} {len(report.comparisons)} rows in {elapsed:.0f}s")
        return True
    except MemoryError:
        print(f"{BAD} ran out of memory — this machine cannot hold the model and "
              f"the comparison at once")
        print("      try: FIRE_SAFETY_MODEL=mini, or compare smaller documents")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"{BAD} {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return False


def post(url: str, payload: dict, timeout: int) -> tuple[bool, str, float]:
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            size = len(response.read())
        return True, f"{size / 1024 / 1024:.2f} MB", time.perf_counter() - started
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(body).get("detail", body)
        except Exception:  # noqa: BLE001
            detail = body[:200]
        return False, f"HTTP {exc.code}: {detail}", time.perf_counter() - started
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}", time.perf_counter() - started


def level_two(baseline: dict, revision: dict, model: str, timeout: int) -> bool:
    rule("2. Against the API directly (port 8000)")
    try:
        urllib.request.urlopen(f"{API}/api/health", timeout=5).read()
    except Exception as exc:  # noqa: BLE001
        print(f"{SKIP} the API is not running: {exc}")
        print("      start it with: uvicorn api.main:app --port 8000")
        return False

    ok, message, elapsed = post(
        f"{API}/api/compare",
        {"version_v1": baseline["id"], "version_v2": revision["id"],
         "strategy": "auto", "model": model},
        timeout,
    )
    print(f"{OK if ok else BAD} {message}  ({elapsed:.0f}s)")

    if not ok:
        alive = True
        try:
            urllib.request.urlopen(f"{API}/api/health", timeout=5).read()
        except Exception:  # noqa: BLE001
            alive = False
        if alive:
            print("      the API is still running — so it rejected or timed out the "
                  "request\n      rather than dying")
        else:
            print("      the API is NO LONGER RUNNING — it was killed during the "
                  "comparison,\n      almost certainly by the operating system "
                  "reclaiming memory")
            print("      check the API terminal for the last thing it printed")
    return ok


def level_three(baseline: dict, revision: dict, model: str, timeout: int) -> bool:
    rule("3. Through the dashboard proxy (port 3000)")
    try:
        urllib.request.urlopen(f"{WEB}/api/health", timeout=5).read()
    except Exception as exc:  # noqa: BLE001
        print(f"{SKIP} the dashboard is not running: {exc}")
        print("      start it with: cd web && npm run dev")
        return False

    ok, message, elapsed = post(
        f"{WEB}/api/compare",
        {"version_v1": baseline["id"], "version_v2": revision["id"],
         "strategy": "auto", "model": model},
        timeout,
    )
    print(f"{OK if ok else BAD} {message}  ({elapsed:.0f}s)")

    if not ok:
        print("      the same request works directly but fails through the proxy, so\n"
              "      the dashboard is the problem. Bypass it:\n"
              "        NEXT_PUBLIC_API_ORIGIN=http://127.0.0.1:8000 npm run dev")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Find where a comparison fails.")
    parser.add_argument("--model", default=None, help="registry key or model id")
    parser.add_argument("--small", action="store_true",
                        help="compare two tiny documents instead of full editions")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--skip-local", action="store_true",
                        help="do not run the in-process comparison")
    args = parser.parse_args()

    model = resolve_model(args.model)
    ram = total_ram_mb()

    print("=" * 58)
    print("Comparison diagnostic")
    print("=" * 58)
    print(f"  model       : {model}{'' if args.model else '  (configured default)'}")
    if ram:
        print(f"  machine RAM : {ram} MB ({ram / 1024:.1f} GB)")
    if ram and ram < 10_000:
        print("  note        : on a machine this size, run the API without --reload"
              "\n                (it doubles the footprint) and serve the dashboard"
              "\n                built rather than in dev mode")

    baseline, revision = pick_versions(args.small)

    results = {}
    if not args.skip_local:
        results["in-process"] = level_one(baseline, revision, model)
    results["direct API"] = level_two(baseline, revision, model, args.timeout)
    results["through proxy"] = level_three(baseline, revision, model, args.timeout)

    rule("Where it stands")
    for name, ok in results.items():
        print(f"  {name:<16}{'ok' if ok else 'FAILED'}")

    failed = [n for n, ok in results.items() if not ok]
    if not failed:
        print("\n  Everything works. If the browser still fails, the problem is in the\n"
              "  browser itself — check its console (F12).")
    else:
        print(f"\n  First failure: {failed[0]} — that is the layer to fix.")

    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
