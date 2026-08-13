"""
Environment Report
──────────────────
Prints everything about a machine that could make this project behave
differently on it. Run on both machines and compare the output side by side —
the lines that differ are the candidates.

    python scripts/env_report.py
    python scripts/env_report.py > mine.txt      # then diff mine.txt theirs.txt
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PACKAGES = [
    "PyMuPDF", "SQLAlchemy", "sentence-transformers", "transformers", "torch",
    "numpy", "scipy", "huggingface-hub", "fastapi", "uvicorn",
    "python-multipart", "pydantic",
]

# Anything set here changes behaviour, so a difference between machines matters.
ENV_VARS = [
    "FIRE_SAFETY_MODEL", "FIRE_SAFETY_MAX_MODELS", "FIRE_SAFETY_PRELOAD",
    "HF_HOME", "HF_HUB_CACHE", "HF_HUB_DISABLE_SYMLINKS", "HF_HUB_OFFLINE",
    "API_ORIGIN", "NEXT_PUBLIC_API_ORIGIN", "NODE_OPTIONS",
    "PYTHONPATH", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV",
]


def section(title: str) -> None:
    print(f"\n{title}")
    print("─" * 58)


def run(*command: str) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        return (result.stdout or result.stderr).strip().splitlines()[0]
    except Exception:  # noqa: BLE001
        return "(not found)"


def main() -> int:
    section("Machine")
    print(f"  platform      {platform.platform()}")
    print(f"  architecture  {platform.machine()} · {platform.architecture()[0]}")
    print(f"  processor     {platform.processor() or 'unknown'}")
    print(f"  cpu count     {os.cpu_count()}")

    try:
        from config import total_ram_mb
        ram = total_ram_mb()
        print(f"  memory        {ram} MB ({ram / 1024:.1f} GB)" if ram else "  memory        unknown")
    except Exception as exc:  # noqa: BLE001
        print(f"  memory        (config import failed: {exc})")

    total, used, free = shutil.disk_usage(os.path.dirname(os.path.abspath(__file__)))
    print(f"  disk free     {free / 1024**3:.1f} GB of {total / 1024**3:.1f} GB")

    section("Python")
    print(f"  version       {sys.version.split()[0]}")
    print(f"  executable    {sys.executable}")
    print(f"  64-bit        {sys.maxsize > 2**32}")

    section("Python packages")
    import importlib.metadata as md
    for name in PACKAGES:
        try:
            print(f"  {name:<24}{md.version(name)}")
        except md.PackageNotFoundError:
            print(f"  {name:<24}NOT INSTALLED")

    section("Node")
    print(f"  node          {run('node', '--version')}")
    print(f"  npm           {run('npm', '--version')}")
    web = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
    for module in ("next", "react", "typescript"):
        path = os.path.join(web, "node_modules", module, "package.json")
        if os.path.isfile(path):
            import json
            with open(path, encoding="utf-8") as handle:
                print(f"  {module:<14}{json.load(handle).get('version')}")
        else:
            print(f"  {module:<14}not installed (run npm ci in web/)")

    section("Model cache")
    try:
        from config import MODEL_NAME, MODEL_REGISTRY, model_is_downloaded
        from huggingface_hub.constants import HF_HUB_CACHE
        print(f"  cache dir     {HF_HUB_CACHE}")
        print(f"  default model {MODEL_NAME}")
        for key, meta in MODEL_REGISTRY.items():
            state = "downloaded" if model_is_downloaded(meta["id"]) else "-"
            print(f"    {key:<8}{state}")
    except Exception as exc:  # noqa: BLE001
        print(f"  (unavailable: {type(exc).__name__}: {exc})")

    section("Environment variables")
    any_set = False
    for name in ENV_VARS:
        value = os.environ.get(name)
        if value is not None:
            print(f"  {name:<28}{value}")
            any_set = True
    if not any_set:
        print("  (none set — all defaults)")

    section("Project data")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for relative in ("fire_safety.db", "corpus/raw", "corpus/text"):
        path = os.path.join(root, relative)
        if os.path.isfile(path):
            print(f"  {relative:<20}{os.path.getsize(path) / 1024**2:.0f} MB")
        elif os.path.isdir(path):
            count = sum(len(files) for _, _, files in os.walk(path))
            print(f"  {relative:<20}{count} files")
        else:
            print(f"  {relative:<20}missing")

    try:
        from database.operations import library_stats
        print(f"  library             {library_stats()}")
    except Exception as exc:  # noqa: BLE001
        print(f"  library             (unreadable: {exc})")

    section("Git")
    print(f"  commit        {run('git', 'rev-parse', '--short', 'HEAD')}")
    print(f"  branch        {run('git', 'rev-parse', '--abbrev-ref', 'HEAD')}")
    status = run("git", "status", "--porcelain")
    print(f"  clean tree    {status in ('', '(not found)')}")

    print("\nRun this on both machines and diff the output; the lines that differ\n"
          "are what to look at. Or skip the comparison entirely and use Docker,\n"
          "where none of the above can differ.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
