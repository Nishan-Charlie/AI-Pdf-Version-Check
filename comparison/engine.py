"""
Semantic Comparison Engine
──────────────────────────
Aligns the clauses of two document versions, scores how far each pair has
moved apart, and renders the word-level redline for every one of them.

Works both ways round: two editions of the same instrument, or two countries'
regulations side by side.
"""

from __future__ import annotations

import time
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
    MAX_UNCHANGED_WORD_DELTA,
    MAX_UNCHANGED_WORD_RATIO,
    MINOR_EDIT_THRESHOLD,
    MODEL_NAME,
    UNCHANGED_THRESHOLD,
)

_ENCODE_BATCH = 64


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
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(self._model_name)
        return self._model

    def encode(self, texts: list[str]) -> np.ndarray:
        """
        Embed texts as unit vectors.

        Normalising here means every similarity downstream is a plain dot
        product, which is what keeps the alignment matrix cheap.
        """
        if not texts:
            return np.zeros((0, 384), dtype=np.float32)
        return self.model.encode(
            texts,
            batch_size=_ENCODE_BATCH,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )

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
        The encoder truncates long clauses, so it can report two clauses as
        identical while hundreds of words differ past the cut-off; the word
        counts are exact, so when they show a substantial edit they override a
        verdict of Unchanged. See MAX_UNCHANGED_WORD_* in config.
        """
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
