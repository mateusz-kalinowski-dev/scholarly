"""Endpointy badawcze — jeden handler chat per wariant ablacji."""
from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Literal

from psycopg import Connection

from app.config import (
    PROFILE_RAG_TIMING,
    RERANK_MIN_SCORE,
    SELF_RAG_POST_GEN_ENABLED,
)
from app.schemas import ChatRequestResearch, ChatResponseV2, QueryRewriteOut, RetrievalMetaV2
from app.services.embeddings import EmbeddingError
from app.services.llm_backend import LlmBackend, use_llm_backend
from app.services.query_rewrite import (
    QueryRewriteResult,
    query_rewrite_to_out,
    rewrite_query_for_retrieval,
)
from app.services.rag import IDK_ANSWER
from app.services.rag_v2 import (
    LLMError,
    build_rag_messages_v2,
    generate_chat,
    hits_to_sources_v2,
)
from app.services.retrieval_baseline0 import search_baseline0_vector
from app.services.retrieval_baseline1 import search_baseline1_vector
from app.services.retrieval_v2 import FtsBackend
from app.services.self_rag_v2 import retrieve_with_self_rag_v2, verify_answer_grounded_v2

ResearchVariant = Literal[
    "baseline0",
    "baseline1",
    "eksperyment1-gin",
    "eksperyment1-bm25",
    "eksperyment2",
    "eksperyment2-openai",
]


@dataclass(frozen=True)
class VariantConfig:
    variant: ResearchVariant
    label: str
    fts_backend: FtsBackend | None = None
    hybrid: bool = False
    rerank: bool = False
    self_rag: bool = False
    llm_backend: LlmBackend = "ollama"


VARIANTS: dict[ResearchVariant, VariantConfig] = {
    "baseline0": VariantConfig(
        variant="baseline0",
        label="Baseline 0 — naiwny chunk, vector only",
    ),
    "baseline1": VariantConfig(
        variant="baseline1",
        label="Baseline 1 — parent-child, vector + title/summary",
    ),
    "eksperyment1-gin": VariantConfig(
        variant="eksperyment1-gin",
        label="Eksperyment 1 — hybrid GIN + rerank",
        fts_backend="gin",
        hybrid=True,
        rerank=True,
    ),
    "eksperyment1-bm25": VariantConfig(
        variant="eksperyment1-bm25",
        label="Eksperyment 1 — hybrid BM25 + rerank",
        fts_backend="bm25",
        hybrid=True,
        rerank=True,
    ),
    "eksperyment2": VariantConfig(
        variant="eksperyment2",
        label="Eksperyment 2 — hybrid BM25 + rerank + Self-RAG",
        fts_backend="bm25",
        hybrid=True,
        rerank=True,
        self_rag=True,
    ),
    "eksperyment2-openai": VariantConfig(
        variant="eksperyment2-openai",
        label="Eksperyment 2 + OpenAI — jak Self-RAG, LLM = gpt-4o-mini (szybki)",
        fts_backend="bm25",
        hybrid=True,
        rerank=True,
        self_rag=True,
        llm_backend="openai",
    ),
}


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def _rewrite_out(rewrite: QueryRewriteResult) -> QueryRewriteOut:
    return query_rewrite_to_out(rewrite)


def _metadata_filters(rewrite: QueryRewriteResult):
    if rewrite.metadata_filters.is_empty():
        return None
    return rewrite.metadata_filters


async def _retrieve_baseline(
    conn: Connection,
    variant: ResearchVariant,
    rewrite: QueryRewriteResult,
    top_k: int,
    *,
    timings: dict[str, float] | None,
) -> tuple[list, RetrievalMetaV2]:
    stage: dict[str, float] = {}
    t0 = time.perf_counter()
    metadata = _metadata_filters(rewrite)
    if variant == "baseline0":
        hits = await search_baseline0_vector(
            conn,
            rewrite.semantic_query,
            top_k,
            metadata_filters=metadata,
            timings=stage,
        )
    else:
        hits = await search_baseline1_vector(
            conn,
            rewrite.semantic_query,
            top_k,
            metadata_filters=metadata,
            timings=stage,
        )
    if timings is not None:
        timings["retrieval_wall_ms"] = _ms(t0)
        timings.update(stage)

    meta = RetrievalMetaV2(
        research_variant=variant,
        rerank_enabled=False,
        self_rag_enabled=False,
        fts_backend=None,
        candidate_limit=len(hits),
        child_candidates=len(hits),
        parent_candidates=len(hits),
        parents_reranked=0,
        rerank_top_score=hits[0].score if hits else None,
        llm_context_count=len(hits),
        retrieval_passes=1,
        retrieval_confidence=hits[0].score if hits else None,
        accepted=bool(hits),
        timings_ms=timings,
    )
    return hits, meta


async def _handle_research_chat_inner(
    body: ChatRequestResearch,
    conn: Connection,
    *,
    variant: ResearchVariant,
) -> ChatResponseV2:
    cfg = VARIANTS[variant]
    t_total = time.perf_counter()
    profile = PROFILE_RAG_TIMING
    timings: dict[str, float] = {}
    if profile:
        timings["llm_is_openai"] = 1.0 if cfg.llm_backend == "openai" else 0.0

    t0 = time.perf_counter()
    rewrite = await rewrite_query_for_retrieval(body.question)
    if profile:
        timings["1_rewrite_ms"] = _ms(t0)

    answer_language = rewrite.user_language

    # Ablacja / Golden QA: zawsze RAG. Oryginalny intent zostaje w query_rewrite
    # (diagnostyka), ale retrieval nigdy nie jest pomijany.
    original_intent = rewrite.intent
    if rewrite.intent != "paper_search":
        semantic = (rewrite.semantic_query or "").strip() or body.question
        rewrite = replace(rewrite, intent="paper_search", semantic_query=semantic)

    query_rewrite = _rewrite_out(rewrite)
    if original_intent != "paper_search":
        query_rewrite = query_rewrite.model_copy(update={"intent": original_intent})

    try:
        if cfg.hybrid:
            t0 = time.perf_counter()
            pipeline = await retrieve_with_self_rag_v2(
                conn,
                body.question,
                rewrite,
                body.top_k,
                self_rag=cfg.self_rag,
                timings=timings if profile else None,
                fts_backend=cfg.fts_backend or "bm25",
            )
            if profile:
                timings["retrieval_wall_ms"] = _ms(t0)
            hits = pipeline.hits
            retrieval_meta = pipeline.meta.model_copy(
                update={"research_variant": variant}
            )
        else:
            hits, retrieval_meta = await _retrieve_baseline(
                conn,
                variant,
                rewrite,
                body.top_k,
                timings=timings if profile else None,
            )
    except EmbeddingError:
        raise

    if not hits:
        if variant == "baseline0":
            raise LookupError(
                "Brak chunków Baseline 0. Uruchom build_baseline0.py."
            )
        answer = IDK_ANSWER
        if profile:
            timings["total_ms"] = _ms(t_total)
        return ChatResponseV2(
            question=body.question,
            answer=answer,
            research_variant=variant,
            query_strategy="rewrite",
            retrieval_query=rewrite.semantic_query,
            user_language=answer_language,
            query_rewrite=query_rewrite,
            retrieval=retrieval_meta,
            timings_ms=timings if profile else None,
            sources=[],
            papers=[],
        )

    system, user = build_rag_messages_v2(
        body.question,
        hits,
        answer_language=answer_language,
    )

    try:
        t0 = time.perf_counter()
        answer = await generate_chat(system, user)
        if profile:
            timings["3_llm_generate_ms"] = _ms(t0)
    except LLMError:
        raise

    answer_verified: bool | None = None
    if cfg.self_rag and SELF_RAG_POST_GEN_ENABLED:
        candidate = answer
        t0 = time.perf_counter()
        answer_verified = await verify_answer_grounded_v2(
            body.question, candidate, hits
        )
        if profile:
            timings["4_verify_ms"] = _ms(t0)

        if not answer_verified and candidate.strip().lower() != IDK_ANSWER.lower():
            retry_system = system + (
                "\n\nCritical: Use ONLY facts explicitly present in the excerpts. "
                "If unsupported, reply exactly: I do not know."
            )
            try:
                t1 = time.perf_counter()
                candidate = await generate_chat(retry_system, user)
                if profile:
                    timings["5_llm_retry_ms"] = _ms(t1)
            except LLMError:
                pass
            t2 = time.perf_counter()
            answer_verified = await verify_answer_grounded_v2(
                body.question, candidate, hits
            )
            if profile:
                timings["6_verify_retry_ms"] = _ms(t2)

        high_trust = (
            retrieval_meta is not None
            and (retrieval_meta.rerank_top_score or 0)
            >= max(RERANK_MIN_SCORE + 0.35, 0.65)
        )
        if not answer_verified:
            if high_trust and candidate.strip().lower() != IDK_ANSWER.lower():
                answer_verified = True
            elif candidate.strip().lower() != IDK_ANSWER.lower():
                candidate = IDK_ANSWER
        answer = candidate
        if retrieval_meta is not None:
            retrieval_meta = retrieval_meta.model_copy(
                update={"answer_verified": answer_verified}
            )

    sources, papers = hits_to_sources_v2(hits)
    if profile:
        timings["total_ms"] = _ms(t_total)

    return ChatResponseV2(
        question=body.question,
        answer=answer,
        research_variant=variant,
        query_strategy="rewrite",
        retrieval_query=rewrite.semantic_query,
        user_language=answer_language,
        query_rewrite=query_rewrite,
        retrieval=retrieval_meta,
        timings_ms=timings if profile else None,
        sources=sources,
        papers=papers,
    )


async def handle_research_chat(
    body: ChatRequestResearch,
    conn: Connection,
    *,
    variant: ResearchVariant,
) -> ChatResponseV2:
    cfg = VARIANTS[variant]
    with use_llm_backend(cfg.llm_backend):
        return await _handle_research_chat_inner(body, conn, variant=variant)
