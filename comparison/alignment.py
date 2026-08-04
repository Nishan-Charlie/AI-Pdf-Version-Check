"""
Clause Alignment
────────────────
Decides which clause in version 2 corresponds to which clause in version 1
before any diffing happens.

Two editions of the same instrument share a numbering scheme, so matching on
the clause number is exact and free. Two different countries' regulations share
nothing but subject matter — Scotland's clause 2.9.3 and England's paragraph
3.14 can carry the same rule under different names — so those are matched on
meaning, vocabulary, and reading position instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np

from comparison.diff import lexical_similarity
from config import (
    ALIGN_ACCEPT_THRESHOLD,
    ALIGN_OPTIMAL_MAX_CELLS,
    ALIGN_TOP_K,
    ALIGN_WEIGHT_EMBEDDING,
    ALIGN_WEIGHT_LEXICAL,
    ALIGN_WEIGHT_POSITION,
    ALIGNMENT_IDENTIFIER,
    ALIGNMENT_SEMANTIC,
    IDENTIFIER_OVERLAP_MIN,
)

Encoder = Callable[[list[str]], np.ndarray]


@dataclass
class AlignedPair:
    """
    One row of the comparison: a clause from each side, or one side only.

    Indices point into the clause lists that were handed to the aligner.
    """

    index_v1: Optional[int]
    index_v2: Optional[int]
    match_score: Optional[float] = None      # composite alignment confidence
    embedding_score: Optional[float] = None  # cosine similarity alone
    method: str = ALIGNMENT_IDENTIFIER

    @property
    def is_pair(self) -> bool:
        return self.index_v1 is not None and self.index_v2 is not None


# ─── Strategy selection ──────────────────────────────────────────────

def identifier_overlap(clauses_v1: list[dict], clauses_v2: list[dict]) -> float:
    """
    Share of clause numbers the two versions have in common.

    Near 1.0 for consecutive editions of one instrument; near 0 across
    countries, where the numbering schemes are unrelated.
    """
    numbers_v1 = {c["clause_number"] for c in clauses_v1}
    numbers_v2 = {c["clause_number"] for c in clauses_v2}
    if not numbers_v1 or not numbers_v2:
        return 0.0
    return len(numbers_v1 & numbers_v2) / min(len(numbers_v1), len(numbers_v2))


def choose_strategy(
    clauses_v1: list[dict],
    clauses_v2: list[dict],
    same_country: bool,
) -> str:
    """
    Pick an alignment method.

    Shared numbering is only trustworthy within one jurisdiction: "2.1" means
    different things in Edinburgh and London, so a cross-country pair always
    goes to semantic alignment however well the numbers happen to coincide.
    """
    if not same_country:
        return ALIGNMENT_SEMANTIC
    if identifier_overlap(clauses_v1, clauses_v2) >= IDENTIFIER_OVERLAP_MIN:
        return ALIGNMENT_IDENTIFIER
    return ALIGNMENT_SEMANTIC


# ─── Identifier alignment ────────────────────────────────────────────

def align_by_identifier(
    clauses_v1: list[dict],
    clauses_v2: list[dict],
) -> list[AlignedPair]:
    """
    Match clauses that carry the same number.

    Numbers repeat legitimately — "Table 1" appears in several sections — so
    repeats are paired in the order they occur rather than collapsed.
    """
    buckets_v1 = _bucket_by_number(clauses_v1)
    buckets_v2 = _bucket_by_number(clauses_v2)

    pairs: list[AlignedPair] = []

    for number, indices_v1 in buckets_v1.items():
        indices_v2 = buckets_v2.get(number, [])
        for position, index_v1 in enumerate(indices_v1):
            index_v2 = indices_v2[position] if position < len(indices_v2) else None
            pairs.append(AlignedPair(index_v1, index_v2, method=ALIGNMENT_IDENTIFIER))

    # Anything left on the right-hand side is new in version 2.
    for number, indices_v2 in buckets_v2.items():
        already_paired = len(buckets_v1.get(number, []))
        for index_v2 in indices_v2[already_paired:]:
            pairs.append(AlignedPair(None, index_v2, method=ALIGNMENT_IDENTIFIER))

    return _sort_pairs(pairs, len(clauses_v1), len(clauses_v2))


def _bucket_by_number(clauses: list[dict]) -> dict[str, list[int]]:
    buckets: dict[str, list[int]] = {}
    for index, clause in enumerate(clauses):
        buckets.setdefault(clause["clause_number"], []).append(index)
    return buckets


# ─── Semantic alignment ──────────────────────────────────────────────

def alignment_text(clause: dict) -> str:
    """
    What the encoder reads for a clause.

    Section and title are prepended because cross-country matching hinges on
    topic: "Means of escape" in one handbook and "Escape routes" in another
    are the same subject even where the body text diverges.
    """
    parts = [
        clause.get("section") or "",
        clause.get("title") or "",
        clause.get("content") or "",
    ]
    return " ".join(part for part in parts if part).strip()


def align_semantic(
    clauses_v1: list[dict],
    clauses_v2: list[dict],
    encoder: Encoder,
) -> list[AlignedPair]:
    """
    Match clauses on meaning, vocabulary, and reading position.

    Runs in three stages so that large cross-country comparisons stay
    tractable: encode once, shortlist the top few candidates per clause, then
    resolve the shortlist into a one-to-one assignment.
    """
    if not clauses_v1 and not clauses_v2:
        return []
    if not clauses_v1:
        return [AlignedPair(None, j, method=ALIGNMENT_SEMANTIC)
                for j in range(len(clauses_v2))]
    if not clauses_v2:
        return [AlignedPair(i, None, method=ALIGNMENT_SEMANTIC)
                for i in range(len(clauses_v1))]

    embeddings_v1 = encoder([alignment_text(c) for c in clauses_v1])
    embeddings_v2 = encoder([alignment_text(c) for c in clauses_v2])

    candidates = _shortlist(clauses_v1, clauses_v2, embeddings_v1, embeddings_v2)
    matches = _resolve(candidates, len(clauses_v1), len(clauses_v2))

    pairs: list[AlignedPair] = []
    matched_v1: set[int] = set()
    matched_v2: set[int] = set()

    for index_v1, index_v2, score, embedding_score in matches:
        pairs.append(AlignedPair(
            index_v1, index_v2,
            match_score=round(float(score), 4),
            embedding_score=round(float(embedding_score), 4),
            method=ALIGNMENT_SEMANTIC,
        ))
        matched_v1.add(index_v1)
        matched_v2.add(index_v2)

    pairs.extend(
        AlignedPair(i, None, method=ALIGNMENT_SEMANTIC)
        for i in range(len(clauses_v1)) if i not in matched_v1
    )
    pairs.extend(
        AlignedPair(None, j, method=ALIGNMENT_SEMANTIC)
        for j in range(len(clauses_v2)) if j not in matched_v2
    )

    return _sort_pairs(pairs, len(clauses_v1), len(clauses_v2))


def _shortlist(
    clauses_v1: list[dict],
    clauses_v2: list[dict],
    embeddings_v1: np.ndarray,
    embeddings_v2: np.ndarray,
    top_k: int = ALIGN_TOP_K,
) -> list[tuple[int, int, float, float]]:
    """
    Candidate pairs, scored.

    Only the top-K nearest clauses on the other side are ever considered, which
    keeps the work linear in document length instead of quadratic. The
    embedding shortlist is then rescored with two signals the encoder is weak
    on: exact technical vocabulary, and where the clause sits in the document.
    """
    count_v1, count_v2 = len(clauses_v1), len(clauses_v2)
    k = min(top_k, count_v2)

    candidates: list[tuple[int, int, float, float]] = []
    chunk = max(1, min(256, count_v1))

    for start in range(0, count_v1, chunk):
        stop = min(start + chunk, count_v1)
        # Embeddings are unit-normalised, so the dot product is the cosine.
        block = embeddings_v1[start:stop] @ embeddings_v2.T

        # argpartition finds the top K without sorting the whole row.
        top_indices = np.argpartition(-block, kth=k - 1, axis=1)[:, :k]

        for row, index_v1 in enumerate(range(start, stop)):
            position_v1 = index_v1 / max(1, count_v1 - 1)

            for index_v2 in top_indices[row]:
                index_v2 = int(index_v2)
                embedding_score = float(block[row, index_v2])

                lexical = lexical_similarity(
                    clauses_v1[index_v1].get("content", ""),
                    clauses_v2[index_v2].get("content", ""),
                )
                position_v2 = index_v2 / max(1, count_v2 - 1)
                positional = 1.0 - abs(position_v1 - position_v2)

                score = (
                    ALIGN_WEIGHT_EMBEDDING * embedding_score
                    + ALIGN_WEIGHT_LEXICAL * lexical
                    + ALIGN_WEIGHT_POSITION * positional
                )

                if score >= ALIGN_ACCEPT_THRESHOLD:
                    candidates.append((index_v1, index_v2, score, embedding_score))

    return candidates


def _resolve(
    candidates: list[tuple[int, int, float, float]],
    count_v1: int,
    count_v2: int,
) -> list[tuple[int, int, float, float]]:
    """
    Turn scored candidates into a one-to-one assignment.

    Small comparisons get the optimal solution. Large ones fall back to
    greedy best-first, which cannot be beaten by much once the shortlist has
    already thrown away the implausible pairs, and stays fast on documents
    with thousands of clauses.
    """
    if not candidates:
        return []

    if count_v1 * count_v2 <= ALIGN_OPTIMAL_MAX_CELLS:
        optimal = _resolve_optimal(candidates, count_v1, count_v2)
        if optimal is not None:
            return optimal

    return _resolve_greedy(candidates)


def _resolve_optimal(
    candidates: list[tuple[int, int, float, float]],
    count_v1: int,
    count_v2: int,
) -> Optional[list[tuple[int, int, float, float]]]:
    """Maximum-weight assignment, when SciPy is available to compute it."""
    try:
        from scipy.optimize import linear_sum_assignment
    except ImportError:
        return None

    scores = np.zeros((count_v1, count_v2), dtype=np.float32)
    embeddings = np.zeros((count_v1, count_v2), dtype=np.float32)
    for index_v1, index_v2, score, embedding_score in candidates:
        scores[index_v1, index_v2] = score
        embeddings[index_v1, index_v2] = embedding_score

    rows, columns = linear_sum_assignment(scores, maximize=True)

    return [
        (int(i), int(j), float(scores[i, j]), float(embeddings[i, j]))
        for i, j in zip(rows, columns)
        # The solver fills unshortlisted cells with zero to square the matrix;
        # those are padding, not matches.
        if scores[i, j] >= ALIGN_ACCEPT_THRESHOLD
    ]


def _resolve_greedy(
    candidates: list[tuple[int, int, float, float]],
) -> list[tuple[int, int, float, float]]:
    """Take the strongest pair repeatedly, skipping clauses already spoken for."""
    used_v1: set[int] = set()
    used_v2: set[int] = set()
    matches: list[tuple[int, int, float, float]] = []

    for index_v1, index_v2, score, embedding_score in sorted(
        candidates, key=lambda c: c[2], reverse=True
    ):
        if index_v1 in used_v1 or index_v2 in used_v2:
            continue
        matches.append((index_v1, index_v2, score, embedding_score))
        used_v1.add(index_v1)
        used_v2.add(index_v2)

    return matches


# ─── Ordering ────────────────────────────────────────────────────────

def _sort_pairs(
    pairs: list[AlignedPair],
    count_v1: int,
    count_v2: int,
) -> list[AlignedPair]:
    """
    Put the comparison into reading order.

    Baseline position drives the order. Clauses that exist only in version 2
    have no baseline position, so theirs is projected from where they sit in
    their own document — which drops them next to the material they belong
    with instead of in a block at the end.
    """
    scale = (count_v1 - 1) / max(1, count_v2 - 1) if count_v2 > 1 else 1.0

    def key(pair: AlignedPair) -> tuple[float, int]:
        if pair.index_v1 is not None:
            return (float(pair.index_v1), 0)
        return (float(pair.index_v2 or 0) * scale, 1)

    return sorted(pairs, key=key)
