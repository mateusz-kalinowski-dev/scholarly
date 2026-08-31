"""Self-RAG v2: lejek retrieval → rerank rodziców → weryfikacja → LLM."""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field

from psycopg import Connection

from app.config import (
    ANCHOR_CHILD_QUOTA,
    PROFILE_RAG_TIMING,
    RAG_CHILD_MAX_CHARS,
    RAG_PARENT_MAX_CHARS,
    RERANK_ENABLED,
    RERANK_MIN_SCORE,
    RERANK_TOP_N,
    SELF_RAG_GRADE_EXCERPTS,
    SELF_RAG_MAX_RETRIES,
    SELF_RAG_MIN_CONFIDENCE,
    child_recall_limit,
    llm_context_limit,
    search_result_limit,
)
from app.schemas import RetrievalMetaV2, SearchHitV2
from app.services.query_rewrite import QueryRewriteResult
from app.services.rag import LLMError, generate_answer
from app.services.reranker_v2 import filter_by_rerank_threshold, rerank_hits_v2
from app.services.retrieval_v2 import (
    FtsBackend,
    collapse_children_to_parents,
    merge_child_hits,
    search_hybrid_v2,
)

logger = logging.getLogger(__name__)

RETRIEVAL_GRADE_PROMPT = """You judge whether arXiv paper excerpts can answer the user's question.

Question:
{question}

Retrieved excerpts:
{excerpts}

Reply with ONLY one JSON object (no markdown):
{{"relevant": true or false, "confidence": number from 0.0 to 1.0, "alternate_query": "concise English search query for retry, or null"}}

Rules:
- relevant=true only if at least one excerpt clearly contains facts needed to answer THE SPECIFIC subject in the question
- if the paper title matches a named entity from the question, treat excerpts from that paper as about that subject
- alternate_query: only when relevant=false; include named entities plus key topic keywords
"""

ANSWER_VERIFY_PROMPT = """You verify whether an answer is grounded in the provided excerpts.

Question:
{question}

Context excerpts:
{excerpts}

Generated answer:
{answer}

Reply with ONLY one JSON object (no markdown):
{{"grounded": true or false, "reason": "brief explanation"}}

Rules:
- grounded=true if the main facts, equations, and numbers in the answer appear in the excerpts (paraphrasing and standard notation are OK)
- grounded=false only when the answer states specific facts, numbers, or formulas that are absent from the excerpts
- do not reject for minor wording differences or combining facts from multiple excerpts
"""


@dataclass
class RetrievalPipelineResult:
    hits: list[SearchHitV2]
    meta: RetrievalMetaV2


@dataclass
class FunnelStats:
    child_candidates: int
    parent_candidates: int
    parents_reranked: int
    rerank_top_score: float | None
    timings_ms: dict[str, float] = field(default_factory=dict)


def _tick() -> float:
    return time.perf_counter()


def _ms(start: float) -> float:
    return round((time.perf_counter() - start) * 1000, 1)


def _format_excerpts_for_grade(hits: list[SearchHitV2], limit: int) -> str:
    parts: list[str] = []
    child_cap = min(RAG_CHILD_MAX_CHARS, 4000)
    parent_cap = min(RAG_PARENT_MAX_CHARS, 4000)
    for i, hit in enumerate(hits[:limit], start=1):
        section = hit.section_name or "N/A"
        child = hit.child_snippet.strip()[:child_cap]
        parent = hit.content.strip()[:parent_cap]
        parts.append(
            f"[{i}] {hit.arxiv_id} | {hit.title} | {section}\n"
            f"Matched child:\n{child}\n"
            f"Parent context:\n{parent}"
        )
    return "\n\n".join(parts) if parts else "(none)"


def _parse_grade_json(raw: str) -> tuple[bool, float, str | None]:
    text = raw.strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    try:
        data = json.loads(text)
        relevant = bool(data.get("relevant"))
        confidence = float(data.get("confidence", 0.0))
        alt = data.get("alternate_query")
        alternate = (alt or "").strip() or None
        return relevant, max(0.0, min(confidence, 1.0)), alternate
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Self-RAG grade parse failed: %s", raw[:200])
        return False, 0.0, None


def _parse_verify_json(raw: str) -> bool:
    text = raw.strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    try:
        data = json.loads(text)
        return bool(data.get("grounded"))
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("Answer verify parse failed: %s", raw[:200])
        return True


async def grade_retrieval_v2(
    question: str,
    hits: list[SearchHitV2],
) -> tuple[bool, float, str | None]:
    if not hits:
        return False, 0.0, None

    prompt = RETRIEVAL_GRADE_PROMPT.format(
        question=question,
        excerpts=_format_excerpts_for_grade(hits, SELF_RAG_GRADE_EXCERPTS),
    )
    try:
        raw = await generate_answer(prompt)
    except LLMError:
        logger.exception("Self-RAG grade — brak alternate_query")
        return False, 0.0, None
    return _parse_grade_json(raw)


async def verify_answer_grounded_v2(
    question: str,
    answer: str,
    hits: list[SearchHitV2],
) -> bool:
    if not hits or not answer.strip():
        return False

    prompt = ANSWER_VERIFY_PROMPT.format(
        question=question,
        excerpts=_format_excerpts_for_grade(hits, SELF_RAG_GRADE_EXCERPTS),
        answer=answer,
    )
    try:
        raw = await generate_answer(prompt)
    except LLMError:
        logger.exception("Answer verify — fallback accept")
        return True
    return _parse_verify_json(raw)


def _hits_cover_anchors(anchors: list[str], hits: list[SearchHitV2]) -> bool:
    if not anchors:
        return True
    for hit in hits:
        blob = f"{hit.title} {hit.arxiv_id} {hit.child_snippet} {hit.content}".lower()
        if any(a.lower() in blob for a in anchors):
            return True
    return False


def _boost_reranked_anchors(
    anchors: list[str],
    hits: list[SearchHitV2],
) -> list[SearchHitV2]:
    if not anchors:
        return hits

    def key(hit: SearchHitV2) -> tuple[int, float]:
        blob = f"{hit.title} {hit.child_snippet} {hit.content}".lower()
        matched = any(a.lower() in blob for a in anchors)
        return (1 if matched else 0, hit.rerank_score or hit.score)

    return sorted(hits, key=key, reverse=True)


def _top_rerank_score(hits: list[SearchHitV2]) -> float | None:
    if not hits:
        return None
    return hits[0].rerank_score if hits[0].rerank_score is not None else hits[0].score


def _build_fallback_alternate_query(rewrite: QueryRewriteResult) -> str:
    anchors = rewrite.anchor_entities
    topical = rewrite.lexical_query
    if anchors:
        return f"{' '.join(anchors)} {topical}".strip()[:200]
    return topical[:200] or rewrite.semantic_query[:200]


async def run_retrieval_funnel(
    conn: Connection,
    question: str,
    rewrite: QueryRewriteResult,
    top_k: int,
    *,
    semantic_query: str | None = None,
    rerank_query: str | None = None,
    for_chat: bool = True,
    timings: dict[str, float] | None = None,
    fts_backend: FtsBackend = "gin",
) -> tuple[list[SearchHitV2], FunnelStats]:
    """
    Krok 1: hybrid → ~100 Dzieci (cały korpus + opcjonalna kotwica)
    Krok 2: collapse → unikalni Rodzice (typowo 40–80)
    Krok 3: rerank Cross-Encoder na do RERANK_TOP_N Rodzicach
    Krok 4: filtr progu rerank + top llm_context_limit do LLM
    """
    embed_query = semantic_query or rewrite.semantic_query
    anchors = rewrite.anchors_for_retrieval(question)
    lexical = rewrite.lexical_query if embed_query == rewrite.semantic_query else embed_query
    metadata = (
        rewrite.metadata_filters
        if not rewrite.metadata_filters.is_empty()
        else None
    )
    child_limit = child_recall_limit(top_k)
    stage: dict[str, float] = {}

    broad_limit = max(child_limit - ANCHOR_CHILD_QUOTA, child_limit // 2)
    t0 = _tick()
    broad_timings: dict[str, float] = {}
    children_broad = await search_hybrid_v2(
        conn,
        embed_query,
        top_k,
        candidate_limit=broad_limit,
        anchor_terms=anchors,
        lexical_query=lexical,
        metadata_filters=metadata,
        title_filter=False,
        timings=broad_timings if (timings is not None or PROFILE_RAG_TIMING) else None,
        fts_backend=fts_backend,
    )
    stage["hybrid_broad_ms"] = _ms(t0)
    if broad_timings:
        stage["hybrid_broad_embed_ms"] = broad_timings.get("embed_ms", 0)
        stage["hybrid_broad_sql_ms"] = broad_timings.get("sql_ms", 0)

    if anchors and ANCHOR_CHILD_QUOTA > 0:
        t0 = _tick()
        anchor_timings: dict[str, float] = {}
        children_anchor = await search_hybrid_v2(
            conn,
            embed_query,
            top_k,
            candidate_limit=ANCHOR_CHILD_QUOTA,
            anchor_terms=anchors,
            lexical_query=lexical,
            metadata_filters=metadata,
            title_filter=True,
            timings=anchor_timings if (timings is not None or PROFILE_RAG_TIMING) else None,
            fts_backend=fts_backend,
        )
        stage["hybrid_anchor_ms"] = _ms(t0)
        if anchor_timings:
            stage["hybrid_anchor_embed_ms"] = anchor_timings.get("embed_ms", 0)
            stage["hybrid_anchor_sql_ms"] = anchor_timings.get("sql_ms", 0)
        children = merge_child_hits(
            children_broad,
            children_anchor,
            limit=child_limit,
        )
    else:
        children = children_broad

    t0 = _tick()
    parents = collapse_children_to_parents(children)
    stage["collapse_ms"] = _ms(t0)

    rq = rerank_query or question
    rerank_pool = parents[:RERANK_TOP_N] if RERANK_TOP_N > 0 else parents

    if RERANK_ENABLED and rerank_pool:
        t0 = _tick()
        reranked = await rerank_hits_v2(rq, rerank_pool, len(rerank_pool))
        stage["rerank_ms"] = _ms(t0)
        reranked = _boost_reranked_anchors(anchors, reranked)
        elite = filter_by_rerank_threshold(reranked, RERANK_MIN_SCORE)
    else:
        reranked = rerank_pool
        elite = rerank_pool

    output_k = llm_context_limit(top_k) if for_chat else search_result_limit(top_k)
    hits = elite[:output_k]

    stats = FunnelStats(
        child_candidates=len(children),
        parent_candidates=len(parents),
        parents_reranked=len(rerank_pool),
        rerank_top_score=_top_rerank_score(reranked),
        timings_ms=stage,
    )
    if timings is not None:
        timings.update(stage)
    return hits, stats


def _retrieval_accepted(
    anchors: list[str],
    hits: list[SearchHitV2],
    rerank_top_score: float | None,
) -> tuple[bool, float]:
    if not hits:
        return False, 0.0

    top_score = rerank_top_score if rerank_top_score is not None else 0.0
    anchors_ok = _hits_cover_anchors(anchors, hits)

    if top_score >= RERANK_MIN_SCORE and anchors_ok:
        confidence = min(0.5 + top_score * 0.5, 0.99)
        return True, confidence

    if top_score >= SELF_RAG_MIN_CONFIDENCE and anchors_ok:
        return True, top_score

    return False, top_score


async def retrieve_with_self_rag_v2(
    conn: Connection,
    question: str,
    rewrite: QueryRewriteResult,
    top_k: int,
    *,
    self_rag: bool = True,
    for_chat: bool = True,
    timings: dict[str, float] | None = None,
    fts_backend: FtsBackend = "gin",
) -> RetrievalPipelineResult:
    passes = 0
    alternate_used: str | None = None
    semantic_query = rewrite.semantic_query
    anchors = rewrite.anchors_for_retrieval(question)
    child_limit = child_recall_limit(top_k)

    meta_base = {
        "rerank_enabled": RERANK_ENABLED,
        "self_rag_enabled": self_rag,
        "fts_backend": fts_backend,
        "candidate_limit": child_limit,
    }

    profile = timings is not None or PROFILE_RAG_TIMING
    pipeline_timings: dict[str, float] = timings if timings is not None else {}

    while passes <= (SELF_RAG_MAX_RETRIES if self_rag else 0):
        passes += 1
        t0 = _tick()
        hits, stats = await run_retrieval_funnel(
            conn,
            question,
            rewrite,
            top_k,
            semantic_query=semantic_query,
            rerank_query=question,
            for_chat=for_chat,
            timings=pipeline_timings if profile else None,
            fts_backend=fts_backend,
        )
        if profile:
            pipeline_timings["retrieval_pass_ms"] = _ms(t0)

        funnel_meta = {
            "child_candidates": stats.child_candidates,
            "parent_candidates": stats.parent_candidates,
            "parents_reranked": stats.parents_reranked,
            "rerank_top_score": stats.rerank_top_score,
            "llm_context_count": len(hits),
        }

        if not self_rag:
            if profile:
                pipeline_timings["retrieval_total_ms"] = round(
                    sum(
                        pipeline_timings.get(k, 0)
                        for k in pipeline_timings
                        if k.endswith("_ms")
                    ),
                    1,
                )
            return RetrievalPipelineResult(
                hits=hits,
                meta=RetrievalMetaV2(
                    **meta_base,
                    **funnel_meta,
                    retrieval_passes=passes,
                    retrieval_confidence=stats.rerank_top_score,
                    alternate_query_used=alternate_used,
                    accepted=True,
                    timings_ms=pipeline_timings if profile else None,
                ),
            )

        accepted, confidence = _retrieval_accepted(
            anchors, hits, stats.rerank_top_score
        )

        if accepted:
            if profile:
                pipeline_timings["retrieval_total_ms"] = round(
                    sum(
                        v
                        for k, v in pipeline_timings.items()
                        if k.endswith("_ms") and k != "retrieval_total_ms"
                    ),
                    1,
                )
            return RetrievalPipelineResult(
                hits=hits,
                meta=RetrievalMetaV2(
                    **meta_base,
                    **funnel_meta,
                    retrieval_passes=passes,
                    retrieval_confidence=confidence,
                    alternate_query_used=alternate_used,
                    accepted=True,
                    timings_ms=pipeline_timings if profile else None,
                ),
            )

        alternate: str | None = None
        if passes <= SELF_RAG_MAX_RETRIES:
            t0 = _tick()
            _, _, alternate = await grade_retrieval_v2(question, hits)
            if profile:
                pipeline_timings["self_rag_grade_ms"] = _ms(t0)
            alternate = alternate or _build_fallback_alternate_query(rewrite)

        if alternate and passes <= SELF_RAG_MAX_RETRIES:
            logger.info(
                "Self-RAG retry (%d, score=%.3f): %s → %s",
                passes,
                stats.rerank_top_score or 0,
                semantic_query[:80],
                alternate[:80],
            )
            alternate_used = alternate
            semantic_query = alternate
            continue

        return RetrievalPipelineResult(
            hits=[],
            meta=RetrievalMetaV2(
                **meta_base,
                **funnel_meta,
                retrieval_passes=passes,
                retrieval_confidence=confidence,
                alternate_query_used=alternate_used,
                accepted=False,
            ),
        )

    return RetrievalPipelineResult(
        hits=[],
        meta=RetrievalMetaV2(
            **meta_base,
            retrieval_passes=passes,
            retrieval_confidence=0.0,
            alternate_query_used=alternate_used,
            accepted=False,
        ),
    )
