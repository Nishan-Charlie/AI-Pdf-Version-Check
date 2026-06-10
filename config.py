"""
Central configuration for the Fire Fighter Document Version Check system.
"""
import os

# ─── Database ────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "fire_safety.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

# ─── Sentence-Transformer Model ─────────────────────────────────────
MODEL_NAME = "all-MiniLM-L6-v2"

# ─── Similarity Thresholds ──────────────────────────────────────────
UNCHANGED_THRESHOLD = 0.95      # >= 0.95 → Unchanged
MINOR_EDIT_THRESHOLD = 0.80     # 0.80 – 0.94 → Minor Edit
                                 # < 0.80 → Significant Change

# ─── Clause Parsing ─────────────────────────────────────────────────
# Regex patterns that identify the start of a new clause/section
CLAUSE_PATTERNS = [
    r"(?m)^(\d+(?:\.\d+)*)\s+",          # 1.2.3 style
    r"(?mi)^(?:section|clause|part)\s+(\d+(?:\.\d+)*)",  # Section 1.2
    r"(?m)^([a-z]\))\s+",                 # a) b) c) style
    r"(?m)^(\([a-z]\))\s+",              # (a) (b) (c) style
    r"(?m)^(\d+\))\s+",                  # 1) 2) 3) style
]
