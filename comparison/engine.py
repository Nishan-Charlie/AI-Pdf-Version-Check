"""
Semantic Comparison Engine
──────────────────────────
Uses Sentence-Transformers to compute semantic similarity between
clause pairs across document versions, classifying each as
Unchanged, Minor Edit, or Significant Change.
"""

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

from config import MODEL_NAME, UNCHANGED_THRESHOLD, MINOR_EDIT_THRESHOLD
from comparison.report import (
    ChangeType,
    ClauseComparison,
    ComparisonReport,
)


class SemanticComparator:
    """
    Compares clauses between two document versions using
    sentence embeddings and cosine similarity.
    """

    def __init__(self, model_name: str = MODEL_NAME):
        """
        Load the Sentence-Transformer model.

        Args:
            model_name: HuggingFace model ID for sentence embeddings.
        """
        self._model = SentenceTransformer(model_name)

    # ── Public API ────────────────────────────────────────────────────

    def compare_texts(self, text_a: str, text_b: str) -> float:
        """
        Compute cosine similarity between two text strings.

        Returns:
            Similarity score in [0, 1].
        """
        embeddings = self._model.encode([text_a, text_b])
        score = cosine_similarity([embeddings[0]], [embeddings[1]])[0][0]
        return float(score)

    def classify_change(self, similarity: float) -> ChangeType:
        """Classify a similarity score into a ChangeType."""
        if similarity >= UNCHANGED_THRESHOLD:
            return ChangeType.UNCHANGED
        elif similarity >= MINOR_EDIT_THRESHOLD:
            return ChangeType.MINOR_EDIT
        else:
            return ChangeType.SIGNIFICANT_CHANGE

    def compare_clauses(
        self,
        clauses_v1: list[dict],
        clauses_v2: list[dict],
        document_name: str = "",
        version_v1_label: str = "V1",
        version_v2_label: str = "V2",
    ) -> ComparisonReport:
        """
        Compare two sets of clauses and produce a full comparison report.

        Clauses are matched by `clause_number`. Unmatched clauses are
        flagged as ADDED or REMOVED.

        Args:
            clauses_v1: List of clause dicts from version 1.
            clauses_v2: List of clause dicts from version 2.
            document_name: Name for the report header.
            version_v1_label: Label for version 1.
            version_v2_label: Label for version 2.

        Returns:
            A ComparisonReport with all clause-level comparisons.
        """
        # Build lookup maps: clause_number → clause dict
        map_v1 = {c["clause_number"]: c for c in clauses_v1}
        map_v2 = {c["clause_number"]: c for c in clauses_v2}

        # Union of all clause numbers, preserving order
        all_numbers = list(dict.fromkeys(
            [c["clause_number"] for c in clauses_v1]
            + [c["clause_number"] for c in clauses_v2]
        ))

        comparisons: list[ClauseComparison] = []

        # Batch-encode for performance: gather all text pairs first
        texts_to_encode = []
        pair_indices = []  # (index_in_all_numbers, "v1_idx", "v2_idx")

        for i, num in enumerate(all_numbers):
            c1 = map_v1.get(num)
            c2 = map_v2.get(num)
            if c1 and c2:
                texts_to_encode.append(c1["content"])
                texts_to_encode.append(c2["content"])
                pair_indices.append((i, len(texts_to_encode) - 2, len(texts_to_encode) - 1))

        # Batch encode all texts at once for efficiency
        embeddings = None
        if texts_to_encode:
            embeddings = self._model.encode(texts_to_encode, show_progress_bar=False)

        # Build similarity lookup
        similarity_map: dict[int, float] = {}
        if embeddings is not None:
            for all_idx, emb_i, emb_j in pair_indices:
                score = cosine_similarity(
                    [embeddings[emb_i]], [embeddings[emb_j]]
                )[0][0]
                similarity_map[all_idx] = float(score)

        # Build comparison results
        for i, num in enumerate(all_numbers):
            c1 = map_v1.get(num)
            c2 = map_v2.get(num)

            title = (c1 or c2 or {}).get("title")

            if c1 and c2:
                # Both versions have this clause
                sim = similarity_map.get(i, 0.0)
                change_type = self.classify_change(sim)
                comparisons.append(ClauseComparison(
                    clause_number=num,
                    title=title,
                    content_v1=c1["content"],
                    content_v2=c2["content"],
                    similarity_score=sim,
                    change_type=change_type,
                ))
            elif c1 and not c2:
                # Clause removed in v2
                comparisons.append(ClauseComparison(
                    clause_number=num,
                    title=title,
                    content_v1=c1["content"],
                    content_v2=None,
                    similarity_score=None,
                    change_type=ChangeType.REMOVED,
                ))
            else:
                # Clause added in v2
                comparisons.append(ClauseComparison(
                    clause_number=num,
                    title=title,
                    content_v1=None,
                    content_v2=c2["content"],
                    similarity_score=None,
                    change_type=ChangeType.ADDED,
                ))

        report = ComparisonReport(
            document_name=document_name,
            version_v1_label=version_v1_label,
            version_v2_label=version_v2_label,
            comparisons=comparisons,
        )
        report.compute_summary()
        return report
