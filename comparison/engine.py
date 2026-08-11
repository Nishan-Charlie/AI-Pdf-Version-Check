"""
Semantic Comparison Engine
──────────────────────────
Aligns the clauses of two document versions, scores how far each pair has
moved apart, and renders the word-level redline for every one of them.

Works both ways round: two editions of the same instrument, or two countries'
regulations side by side.
"""

from __future__ import annotations

import gc
import threading
import time
from collections import OrderedDict
from typing import Optional

import numpy as np

from comparison.alignment import (
    AlignedPair,
    align_by_identifier,
    align_semantic,
    choose_strategy,
    identifier_overlap,
)
from comparison.diff import Redline, redline
from comparison.report import (
    ChangeType,
    ClauseComparison,
    ClauseSide,
    ComparisonReport,
    VersionRef,
)
from config import (
    ALIGNMENT_AUTO,
    ALIGNMENT_SEMANTIC,
    CHUNK_MAX_PER_CLAUSE,
    CHUNK_OVERLAP_WORDS,
    CHUNK_WORDS,
    MAX_LOADED_MODELS,
    MAX_UNCHANGED_WORD_DELTA,
    MAX_UNCHANGED_WORD_RATIO,
    MIN_SIGNIFICANT_WORD_DELTA,
    MIN_SIGNIFICANT_WORD_RATIO,
    MINOR_EDIT_THRESHOLD,
    MODEL_NAME,
    UNCHANGED_THRESHOLD,
    resolve_model,
)

_ENCODE_BATCH = 64

# Encoders are expensive to load and large to hold, so they are shared across
# comparisons and the number resident at once is capped.
_LOADED: "OrderedDict[str, SemanticComparator]" = OrderedDict()

# Serialises loading. The service preloads its default model in a background
# thread while requests are already being served, so without this two threads
# can miss the cache for the same model and each build their own copy —
# briefly doubling the memory the cap exists to bound.
_LOAD_LOCK = threading.RLock()


def get_comparator(model_name: Optional[str] = None) -> "SemanticComparator":
    """
    Fetch a comparator for a model, reusing one already in memory.

    The cache is least-recently-used and bounded by MAX_LOADED_MODELS: letting
    the interface switch models freely would otherwise keep every encoder the
    user has tried resident for the life of the process.
    """
    model_id = resolve_model(model_name)

    with _LOAD_LOCK:
        existing = _LOADED.get(model_id)
        if existing is not None:
            _LOADED.move_to_end(model_id)
            return existing

        comparator = SemanticComparator(model_id)

        # Load here rather than on first encode. A model id that does not
        # exist, or a download that fails, then raises at the point the caller
        # asked for the model — where it can be reported — instead of part-way
        # through a comparison. Nothing broken is left in the cache either.
        comparator.model  # noqa: B018 — the attribute access is the load

        _LOADED[model_id] = comparator

        while len(_LOADED) > MAX_LOADED_MODELS:
            _, evicted = _LOADED.popitem(last=False)
            evicted.unload()

        return comparator


def loaded_models() -> list[str]:
    """Model ids currently resident, least recently used first."""
    return [name for name, c in _LOADED.items() if c.is_loaded]


class SemanticComparator:
    """
    Compares document versions using sentence embeddings.

    The model is loaded on first use rather than at construction, so importing
    this module — or starting the API — does not pay for it.
    """

    def __init__(self, model_name: str = MODEL_NAME):
        self._model_name = model_name
        self._model = None

    # ── Model ────────────────────────────────────────────────────────

    @property
    def model_name(self) -> str:
        """The model id this comparator encodes with."""
        return self._model_name

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def unload(self) -> None:
        """Release the weights. The next use reloads them from disk."""
        self._model = None
        gc.collect()

    def encode(self, texts: list[str]) -> np.ndarray:
        """
        Embed texts as unit vectors, reading every word of them.

        A clause longer than the encoder's window is split into overlapping
        chunks; each is encoded and the results averaged. Without this, the
        model reads only the opening of a long clause and everything after it
        is discarded — measured on this corpus as 16.8% of clauses, with real
        cases scoring 1.0000 similarity across a 1,077-word addition.

        Normalising means every similarity downstream is a plain dot product,
        which is what keeps the alignment matrix cheap.
        """
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)

        # Flatten every text into its chunks, remembering which text each
        # chunk came from, so the whole batch still encodes in one pass.
        chunks: list[str] = []
        owners: list[int] = []
        for index, text in enumerate(texts):
            for chunk in _chunk(text):
                chunks.append(chunk)
                owners.append(index)

        embeddings = self.model.encode(
            chunks,
            batch_size=_ENCODE_BATCH,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

        pooled = np.zeros((len(texts), embeddings.shape[1]), dtype=np.float32)
        np.add.at(pooled, np.asarray(owners), embeddings)

        # Mean of unit vectors is not a unit vector; renormalise so the dot
        # product stays a cosine.
        norms = np.linalg.norm(pooled, axis=1, keepdims=True)
        np.divide(pooled, norms, out=pooled, where=norms > 0)

        return pooled

    @property
    def dimension(self) -> int:
        """Embedding width of the loaded model."""
        return self.model.get_sentence_embedding_dimension()

    # ── Scoring ──────────────────────────────────────────────────────

    def compare_texts(self, text_a: str, text_b: str) -> float:
        """Cosine similarity between two strings, in [0, 1]."""
        embeddings = self.encode([text_a, text_b])
        return float(np.dot(embeddings[0], embeddings[1]))

    @staticmethod
    def classify(similarity: float, marks: Optional[Redline] = None) -> ChangeType:
        """
        Bucket a comparison into a change type.

        Embedding similarity decides, except where the redline contradicts it.
        Similarity is a judgement about meaning made from a truncated, lossy
        reading; the word counts are exact. So where they disagree, the words
        win — in both directions:

            a clause whose text demonstrably differs is never Unchanged;
            a clause that has been largely rewritten is never a Minor Edit.

        See MAX_UNCHANGED_WORD_* and MIN_SIGNIFICANT_WORD_* in config.
        """
        if marks is not None and _largely_rewritten(marks):
            return ChangeType.SIGNIFICANT_CHANGE

        if similarity >= UNCHANGED_THRESHOLD:
            if marks is not None and _substantially_edited(marks):
                return ChangeType.MINOR_EDIT
            return ChangeType.UNCHANGED

        if similarity >= MINOR_EDIT_THRESHOLD:
            return ChangeType.MINOR_EDIT

        return ChangeType.SIGNIFICANT_CHANGE

    # ── Comparison ───────────────────────────────────────────────────

    def compare(
        self,
        clauses_v1: list[dict],
        clauses_v2: list[dict],
        ref_v1: VersionRef,
        ref_v2: VersionRef,
        strategy: str = ALIGNMENT_AUTO,
    ) -> ComparisonReport:
        """
        Compare two clause sets end to end.

        Args:
            clauses_v1: Baseline clauses, in document order.
            clauses_v2: Revised clauses, in document order.
            ref_v1: Which edition the baseline came from.
            ref_v2: Which edition the revision came from.
            strategy: "identifier", "semantic", or "auto" to decide from the
                jurisdictions and the clause numbering.

        Returns:
            A report whose rows are already redlined and classified.
        """
        started = time.perf_counter()

        same_country = ref_v1.country_code == ref_v2.country_code
        overlap = identifier_overlap(clauses_v1, clauses_v2)

        resolved = (
            choose_strategy(clauses_v1, clauses_v2, same_country)
            if strategy == ALIGNMENT_AUTO
            else strategy
        )

        if resolved == ALIGNMENT_SEMANTIC:
            pairs = align_semantic(clauses_v1, clauses_v2, self.encode)
        else:
            pairs = align_by_identifier(clauses_v1, clauses_v2)

        comparisons = self._build_rows(pairs, clauses_v1, clauses_v2, resolved)

        report = ComparisonReport(
            v1=ref_v1,
            v2=ref_v2,
            alignment_method=resolved,
            comparisons=comparisons,
            identifier_overlap=overlap,
            duration_seconds=time.perf_counter() - started,
            model=self._model_name,
        )
        report.compute_summary()
        return report

    def _build_rows(
        self,
        pairs: list[AlignedPair],
        clauses_v1: list[dict],
        clauses_v2: list[dict],
        method: str,
    ) -> list[ClauseComparison]:
        """Score and redline every aligned pair."""
        similarities = self._pair_similarities(pairs, clauses_v1, clauses_v2, method)

        rows: list[ClauseComparison] = []

        for index, pair in enumerate(pairs):
            left = clauses_v1[pair.index_v1] if pair.index_v1 is not None else None
            right = clauses_v2[pair.index_v2] if pair.index_v2 is not None else None

            content_v1 = left["content"] if left else None
            content_v2 = right["content"] if right else None

            marks = redline(content_v1, content_v2)

            if left and right:
                similarity = similarities.get(index, 0.0)
                change_type = self.classify(similarity, marks)
            else:
                similarity = None
                change_type = ChangeType.REMOVED if left else ChangeType.ADDED

            rows.append(ClauseComparison(
                index=index,
                change_type=change_type,
                v1=_side(left),
                v2=_side(right),
                redline=marks.as_dict(),
                similarity_score=round(similarity, 4) if similarity is not None else None,
                match_score=pair.match_score,
                match_method=pair.method,
            ))

        return rows

    def _pair_similarities(
        self,
        pairs: list[AlignedPair],
        clauses_v1: list[dict],
        clauses_v2: list[dict],
        method: str,
    ) -> dict[int, float]:
        """
        Similarity for every matched pair, keyed by row index.

        Semantic alignment has already embedded both documents, so its scores
        are reused rather than recomputed. Identifier alignment has not
        embedded anything yet, so the matched pairs are encoded in one batch.
        """
        matched = [(i, p) for i, p in enumerate(pairs) if p.is_pair]
        if not matched:
            return {}

        if method == ALIGNMENT_SEMANTIC:
            return {
                index: pair.embedding_score
                for index, pair in matched
                if pair.embedding_score is not None
            }

        texts: list[str] = []
        for _, pair in matched:
            texts.append(clauses_v1[pair.index_v1]["content"])
            texts.append(clauses_v2[pair.index_v2]["content"])

        embeddings = self.encode(texts)

        return {
            index: float(np.dot(embeddings[2 * position], embeddings[2 * position + 1]))
            for position, (index, _) in enumerate(matched)
        }


def _chunk(text: str) -> list[str]:
    """
    Split a clause into overlapping windows the encoder can read whole.

    Chunks overlap so a sentence spanning a boundary is still seen intact by
    one of them. Anything short enough is returned as-is, so the common case
    costs nothing.
    """
    words = (text or "").split()
    if not words:
        return [""]
    if len(words) <= CHUNK_WORDS:
        return [text]

    stride = max(1, CHUNK_WORDS - CHUNK_OVERLAP_WORDS)
    chunks = [
        " ".join(words[start:start + CHUNK_WORDS])
        for start in range(0, len(words), stride)
    ]

    return chunks[:CHUNK_MAX_PER_CLAUSE]


def _substantially_edited(marks: Redline) -> bool:
    """
    Whether the redline shows more than typographic drift.

    Either measure is enough on its own: the ratio catches short clauses where
    twenty words is the whole thing, the absolute count catches long ones where
    a thousand added words are still a small share of the text.
    """
    return (
        marks.word_change_ratio > MAX_UNCHANGED_WORD_RATIO
        or (marks.words_added + marks.words_removed) > MAX_UNCHANGED_WORD_DELTA
    )


def _largely_rewritten(marks: Redline) -> bool:
    """
    Whether so much of the clause changed that calling it a minor edit is wrong.

    Catches the case the embedding is worst at: two clauses that open the same
    way and diverge completely afterwards. They score as near-identical because
    the encoder reads the opening, while the redline counts the whole clause.
    """
    return (
        marks.word_change_ratio >= MIN_SIGNIFICANT_WORD_RATIO
        or (marks.words_added + marks.words_removed) >= MIN_SIGNIFICANT_WORD_DELTA
    )


def _side(clause: Optional[dict]) -> Optional[ClauseSide]:
    if clause is None:
        return None
    return ClauseSide(
        clause_number=clause["clause_number"],
        title=clause.get("title"),
        section=clause.get("section"),
        content=clause.get("content", ""),
        ordinal=clause.get("ordinal", 0),
    )
