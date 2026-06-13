"""Self-RAG v2: lejek retrieval → rerank rodziców → weryfikacja → LLM."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from psycopg import Connection

from app.config import (
    ANCHOR_CHILD_QUOTA,
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
from app.services.rag import LLMError, generate_answer
from app.services.reranker_v2 import filter_by_rerank_threshold, rerank_hits_v2
from app.services.retrieval_v2 import (
    anchor_terms_from_text,
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


def _format_excerpts_for_grade(hits: list[SearchHitV2], limit: int) -> str:
    parts: list[str] = []
    for i, hit in enumerate(hits[:limit], start=1):
        section = hit.section_name or "N/A"
        preview = hit.content.replace("\n", " ")[:500]
        parts.append(f"[{i}] {hit.arxiv_id} | {hit.title} | {section}\n{preview}")
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


def _hits_cover_anchors(question: str, hits: list[SearchHitV2]) -> bool:
    anchors = anchor_terms_from_text(question)
    if not anchors:
        return True
    for hit in hits:
        blob = f"{hit.title} {hit.arxiv_id} {hit.child_snippet} {hit.content}".lower()
        if any(a.lower() in blob for a in anchors):
            return True
    return False


def _boost_reranked_anchors(
    question: str,
    hits: list[SearchHitV2],
) -> list[SearchHitV2]:
    anchors = anchor_terms_from_text(question)
    if not anchors:
        return hits

    def key(hit: SearchHitV2) -> tuple[int, float]:
        title = (hit.title or "").lower()
        matched = any(a.lower() in title for a in anchors)
        return (1 if matched else 0, hit.rerank_score or hit.score)

    return sorted(hits, key=key, reverse=True)


def _top_rerank_score(hits: list[SearchHitV2]) -> float | None:
    if not hits:
        return None
    return hits[0].rerank_score if hits[0].rerank_score is not None else hits[0].score


def _build_fallback_alternate_query(question: str, search_query: str) -> str:
    anchors = anchor_terms_from_text(question)
    topical = re.sub(
        r"\b(what|which|where|when|how|are|the|and|for|with|from|that|this)\b",
        " ",
        search_query,
        flags=re.IGNORECASE,
    )
    topical = re.sub(r"\s+", " ", topical).strip()
    if anchors:
        return f"{' '.join(anchors)} {topical}".strip()[:200]
    return topical[:200] or search_query[:200]


async def run_retrieval_funnel(
    conn: Connection,
    question: str,
    search_query: str,
    top_k: int,
    *,
    rerank_query: str | None = None,
    for_chat: bool = True,
) -> tuple[list[SearchHitV2], FunnelStats]:
    """
    Krok 1: hybrid → ~100 Dzieci (cały korpus + opcjonalna kotwica)
    Krok 2: collapse → unikalni Rodzice (typowo 40–80)
    Krok 3: rerank Cross-Encoder na do RERANK_TOP_N Rodzicach
    Krok 4: filtr progu rerank + top llm_context_limit do LLM
    """
    anchors = anchor_terms_from_text(question)
    child_limit = child_recall_limit(top_k)

    broad_limit = max(child_limit - ANCHOR_CHILD_QUOTA, child_limit // 2)
    children_broad = await search_hybrid_v2(
        conn,
        search_query,
        top_k,
        candidate_limit=broad_limit,
        anchor_terms=anchors,
        title_filter=False,
    )

    if anchors and ANCHOR_CHILD_QUOTA > 0:
        children_anchor = await search_hybrid_v2(
            conn,
            search_query,
            top_k,
            candidate_limit=ANCHOR_CHILD_QUOTA,
            anchor_terms=anchors,
            title_filter=True,
        )
        children = merge_child_hits(
            children_broad,
            children_anchor,
            limit=child_limit,
        )
    else:
        children = children_broad

    parents = collapse_children_to_parents(children)

    rq = rerank_query or question
    rerank_pool = parents[:RERANK_TOP_N] if RERANK_TOP_N > 0 else parents

    if RERANK_ENABLED and rerank_pool:
        reranked = await rerank_hits_v2(rq, rerank_pool, len(rerank_pool))
        reranked = _boost_reranked_anchors(question, reranked)
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
    )
    return hits, stats


def _retrieval_accepted(
    question: str,
    hits: list[SearchHitV2],
    rerank_top_score: float | None,
) -> tuple[bool, float]:
    if not hits:
        return False, 0.0

    top_score = rerank_top_score if rerank_top_score is not None else 0.0
    anchors_ok = _hits_cover_anchors(question, hits)

    if top_score >= RERANK_MIN_SCORE and anchors_ok:
        confidence = min(0.5 + top_score * 0.5, 0.99)
        return True, confidence

    if top_score >= SELF_RAG_MIN_CONFIDENCE and anchors_ok:
        return True, top_score

    return False, top_score


async def retrieve_with_self_rag_v2(
    conn: Connection,
    question: str,
    search_query: str,
    top_k: int,
    *,
    self_rag: bool = True,
    for_chat: bool = True,
) -> RetrievalPipelineResult:
    passes = 0
    alternate_used: str | None = None
    query = search_query
    child_limit = child_recall_limit(top_k)

    meta_base = {
        "rerank_enabled": RERANK_ENABLED,
        "self_rag_enabled": self_rag,
        "candidate_limit": child_limit,
    }

    while passes <= (SELF_RAG_MAX_RETRIES if self_rag else 0):
        passes += 1
        hits, stats = await run_retrieval_funnel(
            conn,
            question,
            query,
            top_k,
            rerank_query=question,
            for_chat=for_chat,
        )

        funnel_meta = {
            "child_candidates": stats.child_candidates,
            "parent_candidates": stats.parent_candidates,
            "parents_reranked": stats.parents_reranked,
            "rerank_top_score": stats.rerank_top_score,
            "llm_context_count": len(hits),
        }

        if not self_rag:
            return RetrievalPipelineResult(
                hits=hits,
                meta=RetrievalMetaV2(
                    **meta_base,
                    **funnel_meta,
                    retrieval_passes=passes,
                    retrieval_confidence=stats.rerank_top_score,
                    alternate_query_used=alternate_used,
                    accepted=True,
                ),
            )

        accepted, confidence = _retrieval_accepted(
            question, hits, stats.rerank_top_score
        )

        if accepted:
            return RetrievalPipelineResult(
                hits=hits,
                meta=RetrievalMetaV2(
                    **meta_base,
                    **funnel_meta,
                    retrieval_passes=passes,
                    retrieval_confidence=confidence,
                    alternate_query_used=alternate_used,
                    accepted=True,
                ),
            )

        alternate: str | None = None
        if passes <= SELF_RAG_MAX_RETRIES:
            _, _, alternate = await grade_retrieval_v2(question, hits)
            alternate = alternate or _build_fallback_alternate_query(question, query)

        if alternate and passes <= SELF_RAG_MAX_RETRIES:
            logger.info(
                "Self-RAG retry (%d, score=%.3f): %s → %s",
                passes,
                stats.rerank_top_score or 0,
                query[:80],
                alternate[:80],
            )
            alternate_used = alternate
            query = alternate
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
