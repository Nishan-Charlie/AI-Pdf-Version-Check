"""
Central configuration for the Fire Safety Regulation Comparison system.

Everything that is jurisdiction-specific lives here so that adding a new
country is a data change rather than a code change.
"""
import os
import sys

# ─── Windows: model cache without symlinks ──────────────────────────
# HuggingFace stores each file once as a blob and symlinks it into the
# snapshot. Creating a symlink on Windows needs SeCreateSymbolicLinkPrivilege,
# which ordinary accounts do not hold, so the download fails part-way with
#
#     [WinError 1314] A required privilege is not held by the client
#
# leaving a half-written cache behind. Copying instead costs some duplicated
# disk — a few hundred megabytes across the four models — and always works.
#
# Set before huggingface_hub is imported anywhere, because it reads this into a
# constant at import time. An explicit setting from the environment wins, so
# anyone running with Developer Mode on can keep symlinks.
if sys.platform == "win32":
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")

# ─── Paths ───────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "fire_safety.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

CORPUS_DIR = os.path.join(BASE_DIR, "corpus")
CORPUS_RAW_DIR = os.path.join(CORPUS_DIR, "raw")     # downloaded PDFs
CORPUS_TEXT_DIR = os.path.join(CORPUS_DIR, "text")   # extracted text corpus

# ─── Sentence-Transformer Model ─────────────────────────────────────
# Set FIRE_SAFETY_MODEL to any of these keys (or a HuggingFace model id) to
# switch. Window is what the encoder reads before truncating; clauses longer
# than that are chunked and pooled rather than cut off (see CHUNK_* below).
# `size_mb` is the download. `ram_mb` is what the loaded model costs the
# service, which is the figure that decides whether a machine can run it:
# PyTorch's runtime alone is most of a gigabyte before any weights are read.
MODEL_REGISTRY = {
    # Fast, small, and the weakest — kept so results in earlier reports can
    # still be reproduced, and the only comfortable choice on a small machine.
    "mini":   {"id": "all-MiniLM-L6-v2",        "dim": 384,  "window": 256,  "size_mb": 90,   "ram_mb": 900},
    # Strong general-purpose sentence encoder.
    "mpnet":  {"id": "all-mpnet-base-v2",       "dim": 768,  "window": 384,  "size_mb": 420,  "ram_mb": 1500},
    # Default: better retrieval quality than mpnet and twice MiniLM's window,
    # which matters because 16.8% of corpus clauses overflow 256 tokens.
    "bge":    {"id": "BAAI/bge-base-en-v1.5",   "dim": 768,  "window": 512,  "size_mb": 440,  "ram_mb": 1600},
    # Highest quality, noticeably slower and much larger.
    "bge-lg": {"id": "BAAI/bge-large-en-v1.5",  "dim": 1024, "window": 512,  "size_mb": 1340, "ram_mb": 3000},
}

# Below this much physical memory, the dashboard warns that a heavy model will
# contend with its own compiler. Set from the failure it is meant to prevent:
# an 8 GB machine running this service and `next dev` at once.
LOW_MEMORY_THRESHOLD_MB = 10_000

# Small by default, so the service fits alongside the dashboard on an ordinary
# machine — roughly 900 MB resident against bge-base's 1.6 GB. It is the
# weakest of the four and its 256-token window truncates more clauses, but
# chunking means the whole clause is still read (see CHUNK_* below), and a
# service that runs everywhere beats one that is killed under memory pressure.
#
# Set FIRE_SAFETY_MODEL=bge for the stronger default on a machine with room;
# that is what the figures in RESEARCH_FINDINGS.md were measured with.
DEFAULT_MODEL_KEY = "mini"

# Load the default encoder when the service starts rather than on the first
# comparison, so the first comparison is not several seconds slower than the
# rest for no visible reason. Set to "0" to defer it.
PRELOAD_DEFAULT_MODEL = os.environ.get("FIRE_SAFETY_PRELOAD", "1") != "0"

# Whether that preload may also *download* a model it does not have.
#
# Off by default: fetching hundreds of megabytes unasked, on a developer's
# machine, is not the service's decision — the dashboard offers it with a
# progress bar instead.
#
# On in the container, where it is the right default. A fresh model volume
# otherwise leaves the first comparison to download the encoder inside the
# request, which takes long enough to exceed the dashboard's proxy timeout and
# surfaces as a 500 or `socket hang up` on the user's first click.
PRELOAD_MAY_DOWNLOAD = os.environ.get("FIRE_SAFETY_PRELOAD_DOWNLOAD", "0") != "0"

_requested = os.environ.get("FIRE_SAFETY_MODEL", DEFAULT_MODEL_KEY)
MODEL_NAME = MODEL_REGISTRY.get(_requested, {}).get("id", _requested)

# How many encoders may be resident at once.
#
# One, by default. A loaded encoder costs far more than its download: PyTorch's
# own footprint plus weights and activations puts bge-base near 1.5 GB, and
# holding two was measured pushing this service past 3.6 GB resident. On an 8 GB
# machine that leaves nothing for the dashboard's compiler, which fails with
# ERR_MEMORY_ALLOCATION_FAILED — the dashboard dying because of a setting on
# the Python side.
#
# Raise it if you have the headroom and switch models often; the cost of the
# default is a few seconds reloading from disk when you do.
MAX_LOADED_MODELS = max(1, int(os.environ.get("FIRE_SAFETY_MAX_MODELS", "1")))


def _cgroup_limit_mb() -> int:
    """
    Memory this process is actually allowed, when it runs under a cgroup.

    A container sees the host's physical memory through the ordinary
    interfaces, so asking the machine how much RAM it has reports the whole
    host — or the whole Docker VM — while the kernel will kill this process for
    exceeding a far smaller cap. The cap is what matters, and only the cgroup
    knows it.

    Returns 0 when there is no limit, or none can be read.
    """
    candidates = (
        "/sys/fs/cgroup/memory.max",                   # cgroup v2
        "/sys/fs/cgroup/memory/memory.limit_in_bytes",  # cgroup v1
    )

    for path in candidates:
        try:
            with open(path, encoding="utf-8") as handle:
                raw = handle.read().strip()
        except OSError:
            continue

        if raw == "max":
            return 0
        try:
            value = int(raw)
        except ValueError:
            continue

        # "Unlimited" is expressed as a number near the word size rather than a
        # sentinel, so anything absurd means no cap.
        if value <= 0 or value >= 1 << 62:
            return 0
        return value // (1024 ** 2)

    return 0


def total_ram_mb() -> int:
    """
    Memory this process may actually use, or 0 if it cannot be determined.

    Under a container this is the cgroup cap rather than the machine's RAM:
    reporting the host's 16 GB while the container may use 1 GB made every
    model look like it would fit, so nothing warned before the kernel killed
    the service mid-comparison.

    Used to warn before loading a model that will not fit. Deliberately
    dependency-free — psutil is not worth requiring for one number.
    """
    capped = _cgroup_limit_mb()
    physical = _physical_ram_mb()

    if capped and physical:
        return min(capped, physical)
    return capped or physical


def _physical_ram_mb() -> int:
    """Memory installed in the machine, ignoring any cgroup cap."""
    try:
        if hasattr(os, "sysconf") and "SC_PHYS_PAGES" in os.sysconf_names:
            return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") // (1024 ** 2)
    except (ValueError, OSError):
        pass

    try:
        import ctypes

        class _MemoryStatus(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(_MemoryStatus)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
        return int(status.ullTotalPhys // (1024 ** 2))
    except Exception:  # noqa: BLE001 — a missing figure is not an error
        return 0


def resolve_model(requested: str | None) -> str:
    """
    Turn a registry key, a HuggingFace id, or nothing into a model id.

    Unknown values pass through unchanged so any Sentence-Transformer model can
    be named directly without being registered first.
    """
    if not requested:
        return MODEL_NAME
    return MODEL_REGISTRY.get(requested, {}).get("id", requested)


def model_key_for(model_id: str) -> str | None:
    """The registry key a model id belongs to, if it is a registered one."""
    for key, entry in MODEL_REGISTRY.items():
        if entry["id"] == model_id:
            return key
    return None


def hf_repo_id(model_id: str) -> str:
    """
    The HuggingFace repository a model id refers to.

    Sentence-Transformers publishes its own models under an org, so a bare name
    like "all-MiniLM-L6-v2" lives at "sentence-transformers/all-MiniLM-L6-v2".
    """
    return model_id if "/" in model_id else f"sentence-transformers/{model_id}"


# What a snapshot must contain to be loadable. A repository can be present on
# disk without being usable — an interrupted download leaves the folder, and
# sometimes a refs entry, with no weights beneath it.
_REQUIRED_FILES = ("config.json", "modules.json")
_WEIGHT_FILES = ("model.safetensors", "pytorch_model.bin")


def model_is_downloaded(model_id: str) -> bool:
    """
    Whether a *usable* copy of the model is on disk.

    Checks for the files a load actually needs rather than for the cache
    folder. Testing only the folder reports a half-finished download as ready,
    after which loading fails with a confusing error — the service says the
    model is available, then cannot open it.
    """
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
    except ImportError:
        return False

    candidates = {model_id, hf_repo_id(model_id)}

    for name in candidates:
        snapshots = os.path.join(
            HF_HUB_CACHE, "models--" + name.replace("/", "--"), "snapshots"
        )
        if not os.path.isdir(snapshots):
            continue

        for revision in os.listdir(snapshots):
            path = os.path.join(snapshots, revision)
            if not os.path.isdir(path):
                continue
            present = set(os.listdir(path))
            if all(f in present for f in _REQUIRED_FILES) and any(
                f in present for f in _WEIGHT_FILES
            ):
                return True

    return False

# ─── Long-Clause Chunking ───────────────────────────────────────────
# No encoder window covers this corpus: the longest clause is 16,910 word
# pieces. Rather than truncate, a clause that overflows is split into
# overlapping windows, each encoded, and the results averaged — so the whole
# clause contributes to its embedding instead of only the opening.
CHUNK_WORDS = 220           # words per window, comfortably inside 512 pieces
CHUNK_OVERLAP_WORDS = 40    # carried between windows so edges are not orphaned
CHUNK_MAX_PER_CLAUSE = 24   # ceiling on work for pathological clauses

# ─── Similarity Thresholds ──────────────────────────────────────────
UNCHANGED_THRESHOLD = 0.95      # >= 0.95 → Unchanged
MINOR_EDIT_THRESHOLD = 0.80     # 0.80 – 0.94 → Minor Edit
                                # < 0.80 → Significant Change

# ─── Word-Evidence Guard ────────────────────────────────────────────
# The encoder reads at most 256 word pieces, roughly 180 words. Beyond that
# a clause is truncated, so two clauses sharing an opening can differ by any
# amount afterwards and still embed identically — measured at 16.8% of the
# corpus, with real cases scoring 1.0000 similarity across a 1,077-word
# addition. The redline is not truncated and counts those words correctly.
#
# So where the two disagree, the words win. The guard works in both
# directions, because the embedding errs both ways:
#
#   too mild  — a clause reported Unchanged while its text demonstrably
#               differs, which is the truncation case above.
#   too mild  — a clause reported a Minor Edit while most of it was rewritten.
#               Measured at 44 of 617 rows before this guard existed, the worst
#               being a clause with 92% of its words changed (+2,020 / -628).
#
# Thresholds sit above typographic noise (hyphenation, spacing) and below any
# edit of substance.
MAX_UNCHANGED_WORD_RATIO = 0.05   # above this, no longer "Unchanged"
MAX_UNCHANGED_WORD_DELTA = 20     # or this many words, whichever trips first

MIN_SIGNIFICANT_WORD_RATIO = 0.35  # above this, no longer a "Minor Edit"
MIN_SIGNIFICANT_WORD_DELTA = 200   # or this many words rewritten outright

# ─── Jurisdictions ──────────────────────────────────────────────────
# `parser_profile` selects the clause-numbering grammar used at ingest time.
# `sigil` is the two-letter mark the UI prints next to a document.
JURISDICTIONS: list[dict] = [
    {
        "code": "EW",
        "name": "England & Wales",
        "sigil": "EW",
        "authority": "Ministry of Housing, Communities & Local Government",
        "instrument": "Approved Document B",
        "parser_profile": "approved_document",
    },
    {
        "code": "SC",
        "name": "Scotland",
        "sigil": "SC",
        "authority": "Scottish Government Building Standards Division",
        "instrument": "Technical Handbook",
        "parser_profile": "technical_handbook",
    },
    {
        "code": "NI",
        "name": "Northern Ireland",
        "sigil": "NI",
        "authority": "Department of Finance (NI)",
        "instrument": "Technical Booklet E",
        "parser_profile": "technical_booklet",
    },
    {
        "code": "IE",
        "name": "Republic of Ireland",
        "sigil": "IE",
        "authority": "Department of Housing, Local Government and Heritage",
        "instrument": "Technical Guidance Document B",
        "parser_profile": "technical_guidance",
    },
    {
        "code": "BSI",
        "name": "British Standards",
        "sigil": "BS",
        "authority": "British Standards Institution",
        "instrument": "BS 9999 / BS 9991 / BS 7974",
        "parser_profile": "british_standard",
    },
    {
        "code": "INT",
        "name": "Other / International",
        "sigil": "IN",
        "authority": "",
        "instrument": "",
        "parser_profile": "generic",
    },
]

JURISDICTION_BY_CODE = {j["code"]: j for j in JURISDICTIONS}
DEFAULT_JURISDICTION = "INT"

# Sentinel accepted by the ingest API: detect the profile from the text itself.
AUTO_JURISDICTION = "AUTO"


def jurisdiction_name(code: str | None) -> str:
    """Human-readable name for a jurisdiction code."""
    if not code:
        return "Unassigned"
    return JURISDICTION_BY_CODE.get(code, {}).get("name", code)


def parser_profile_for(code: str | None) -> str:
    """Parser profile registered against a jurisdiction code."""
    if not code:
        return "generic"
    return JURISDICTION_BY_CODE.get(code, {}).get("parser_profile", "generic")


# ─── Clause Alignment ───────────────────────────────────────────────
# How clause pairs are matched between two versions.
#   "identifier" — match on clause number (same document lineage)
#   "semantic"   — match on meaning + position (cross-country)
#   "auto"       — pick per comparison from clause-number overlap
ALIGNMENT_AUTO = "auto"
ALIGNMENT_IDENTIFIER = "identifier"
ALIGNMENT_SEMANTIC = "semantic"

# Below this share of shared clause numbers, "auto" falls back to semantic.
IDENTIFIER_OVERLAP_MIN = 0.35

# Composite score for semantic alignment: embedding similarity carries the
# decision, term overlap rescues technical vocabulary the encoder blurs
# ("door", "sprinkler"), position keeps regulations in reading order.
ALIGN_WEIGHT_EMBEDDING = 0.72
ALIGN_WEIGHT_LEXICAL = 0.18
ALIGN_WEIGHT_POSITION = 0.10

# A candidate pair below this composite score is not a match; both clauses
# are reported as Removed / Added instead of a bad pairing.
ALIGN_ACCEPT_THRESHOLD = 0.42

# Candidate generation: only the top-K most similar clauses on the other side
# are considered for each clause. Keeps large cross-country runs tractable.
ALIGN_TOP_K = 12

# Above this many candidate pairs, the optimal assignment solver is skipped
# in favour of mutual-best-match (linear rather than cubic).
ALIGN_OPTIMAL_MAX_CELLS = 250_000

# ─── Ingestion ──────────────────────────────────────────────────────
# Clauses shorter than this are folded into the preceding clause rather than
# stored separately — stops list fragments ("a)", "(ii)") becoming records.
MIN_CLAUSE_CHARS = 60

# Guard against runaway extraction on malformed PDFs.
MAX_CLAUSES_PER_VERSION = 20_000

# ─── Search ─────────────────────────────────────────────────────────
CORPUS_SEARCH_LIMIT = 200
