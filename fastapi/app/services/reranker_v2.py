"""Cross-encoder reranking na poziomie Rodziców (parent context)."""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache

from app.config import (
    RERANK_BATCH_SIZE,
    RERANK_DEVICE,
    RERANK_MAX_CHARS,
    RERANK_MIN_SCORE,
    RERANK_MODEL,
    RAG_CHILD_MAX_CHARS,
    RAG_PARENT_MAX_CHARS,
)
from app.schemas import SearchHitV2

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_cross_encoder():
    from sentence_transformers import CrossEncoder
    import torch

    if RERANK_DEVICE == "cpu":
        device = "cpu"
    elif RERANK_DEVICE == "cuda":
        device = "cuda" if torch.cuda.is_available() else "cpu"
    else:
        device = "cuda" if torch.cuda.is_available() else "cpu"

    if RERANK_DEVICE == "cuda" and device == "cpu":
        logger.warning(
            "RERANK_DEVICE=cuda, ale brak GPU — reranker działa na CPU"
        )

    logger.info("Ładowanie rerankera: %s (device=%s)", RERANK_MODEL, device)
    return CrossEncoder(RERANK_MODEL, max_length=512, device=device)


def _passage_for_rerank(hit: SearchHitV2) -> str:
    """Reranker: pełny child (trafienie) + parent (kontekst sekcji)."""
    section = hit.section_name or ""
    child = hit.child_snippet.strip()[:RAG_CHILD_MAX_CHARS]
    parent = hit.content.strip()[:RAG_PARENT_MAX_CHARS]
    text = (
        f"Paper: {hit.title}\n"
        f"Section: {section}\n"
        f"Matched child passage:\n{child}\n"
        f"Parent section context:\n{parent}"
    )
    return text[:RERANK_MAX_CHARS]


def _rerank_sync(query: str, hits: list[SearchHitV2], top_k: int) -> list[SearchHitV2]:
    if not hits:
        return []

    model = _load_cross_encoder()
    pairs = [(query, _passage_for_rerank(h)) for h in hits]
    scores = model.predict(
        pairs,
        batch_size=RERANK_BATCH_SIZE,
        show_progress_bar=False,
    )

    ranked: list[SearchHitV2] = []
    for hit, rerank_score in sorted(
        zip(hits, scores, strict=True),
        key=lambda x: float(x[1]),
        reverse=True,
    ):
        ranked.append(
            hit.model_copy(
                update={
                    "rerank_score": float(rerank_score),
                    "score": float(rerank_score),
                }
            )
        )

    return ranked[:top_k]


def filter_by_rerank_threshold(
    hits: list[SearchHitV2],
    min_score: float = RERANK_MIN_SCORE,
) -> list[SearchHitV2]:
    return [h for h in hits if (h.rerank_score or 0.0) >= min_score]


async def rerank_hits_v2(
    query: str,
    hits: list[SearchHitV2],
    top_k: int,
) -> list[SearchHitV2]:
    if not hits:
        return []
    return await asyncio.to_thread(_rerank_sync, query, hits, top_k)
