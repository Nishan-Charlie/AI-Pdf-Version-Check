"""
Central configuration for the Fire Safety Regulation Comparison system.

Everything that is jurisdiction-specific lives here so that adding a new
country is a data change rather than a code change.
"""
import os

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
MODEL_REGISTRY = {
    # Fast, small, and the weakest — kept so results in earlier reports can
    # still be reproduced.
    "mini":   {"id": "all-MiniLM-L6-v2",        "dim": 384,  "window": 256,  "size_mb": 90},
    # Strong general-purpose sentence encoder.
    "mpnet":  {"id": "all-mpnet-base-v2",       "dim": 768,  "window": 384,  "size_mb": 420},
    # Default: better retrieval quality than mpnet and twice MiniLM's window,
    # which matters because 16.8% of corpus clauses overflow 256 tokens.
    "bge":    {"id": "BAAI/bge-base-en-v1.5",   "dim": 768,  "window": 512,  "size_mb": 440},
    # Highest quality, noticeably slower and much larger.
    "bge-lg": {"id": "BAAI/bge-large-en-v1.5",  "dim": 1024, "window": 512,  "size_mb": 1340},
}

DEFAULT_MODEL_KEY = "bge"

_requested = os.environ.get("FIRE_SAFETY_MODEL", DEFAULT_MODEL_KEY)
MODEL_NAME = MODEL_REGISTRY.get(_requested, {}).get("id", _requested)

# How many encoders may be resident at once. Each is hundreds of megabytes, so
# switching models freely in the UI would otherwise exhaust memory.
MAX_LOADED_MODELS = 2


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


def model_is_downloaded(model_id: str) -> bool:
    """
    Whether the weights are already on disk.

    Lets the interface distinguish "switch to this" from "download 1.3 GB
    first", rather than appearing to hang on the first comparison.
    """
    try:
        from huggingface_hub.constants import HF_HUB_CACHE
    except ImportError:
        return False

    # Sentence-Transformers publishes bare names under its own org, so a model
    # given as "all-MiniLM-L6-v2" caches as "sentence-transformers/all-...".
    candidates = [model_id]
    if "/" not in model_id:
        candidates.append(f"sentence-transformers/{model_id}")

    return any(
        os.path.isdir(os.path.join(HF_HUB_CACHE, "models--" + name.replace("/", "--")))
        for name in candidates
    )

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
