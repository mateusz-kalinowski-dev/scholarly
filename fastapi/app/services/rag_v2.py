"""RAG v2 — kontekst: pełny child (trafienie) + parent (szersza sekcja)."""
from __future__ import annotations

from app.config import LLM_MAX_CONTEXT_CHARS, RAG_CHILD_MAX_CHARS, RAG_PARENT_MAX_CHARS
from app.schemas import SearchHitV2, SourceChunkV2, SourcePaper
from app.services.rag import (
    IDK_ANSWER,
    LLMError,
    LLM_ONLY_SYSTEM_PROMPT,
    generate_chat,
)

RAG_V2_SYSTEM_PROMPT = """You are Scholarly, a scientific Q&A assistant for arXiv CS papers.

You receive numbered context excerpts [1], [2], … Each excerpt has:
- Matched passage: the child chunk that matched retrieval (often a table row or precise paragraph).
- Broader section context: the parent chunk (surrounding section prose).

Answer ONLY using information present in these excerpts. Prefer the matched passage for numbers and tables; use parent context for surrounding methodology. Do not use prior knowledge.

Answer format (required):
- Write 2–4 complete sentences in plain prose (no markdown, no bullet lists).
- Include concrete facts: methods, metrics, percentages, equations, comparisons.
- Cite excerpts with [n] when a fact comes from that excerpt.
- Preserve mathematical notation if present in the excerpt.

Partial answers:
- If excerpts partially answer the question, answer what is supported and note what is missing.

When information is missing:
- If no excerpt contains relevant information, reply with exactly: I do not know.
- Do not guess."""


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "…"


def hits_to_sources_v2(
    hits: list[SearchHitV2],
) -> tuple[list[SourceChunkV2], list[SourcePaper]]:
    sources: list[SourceChunkV2] = []
    papers_map: dict[str, SourcePaper] = {}

    for h in hits:
        sources.append(
            SourceChunkV2(
                child_id=h.child_id,
                parent_id=h.parent_id,
                paper_id=h.paper_id,
                arxiv_id=h.arxiv_id,
                title=h.title,
                section_name=h.section_name,
                child_snippet=_clip(h.child_snippet, RAG_CHILD_MAX_CHARS),
                content=_clip(h.content, RAG_PARENT_MAX_CHARS),
                score=h.score,
                hybrid_score=h.hybrid_score,
                rerank_score=h.rerank_score,
                vector_distance=h.vector_distance,
                text_score=h.text_score,
            )
        )
        if h.paper_id not in papers_map:
            papers_map[h.paper_id] = SourcePaper(
                paper_id=h.paper_id,
                arxiv_id=h.arxiv_id,
                title=h.title,
                arxiv_url=h.arxiv_url,
            )
    return sources, list(papers_map.values())


def _answer_language_instruction(answer_language: str | None) -> str:
    if not answer_language:
        return ""
    return (
        f"\n\nLanguage: Write the answer in {answer_language}. "
        "Context may be in English; translate while keeping numbers and formulas accurate."
    )


def _format_context_block_v2(index: int, hit: SearchHitV2) -> str:
    section = hit.section_name or "N/A"
    if hit.subsection_name:
        section = f"{section} / {hit.subsection_name}"
    child = _clip(hit.child_snippet.strip(), RAG_CHILD_MAX_CHARS)
    parent = _clip(hit.content.strip(), RAG_PARENT_MAX_CHARS)
    return (
        f"--- Excerpt [{index}] ---\n"
        f"Paper: {hit.title}\n"
        f"arXiv: {hit.arxiv_id}\n"
        f"Section: {section}\n"
        f"Matched passage (retrieved child):\n{child}\n"
        f"Broader section context (parent):\n{parent}\n"
    )


def build_rag_messages_v2(
    question: str,
    hits: list[SearchHitV2],
    *,
    answer_language: str | None = None,
) -> tuple[str, str]:
    context_parts: list[str] = []
    used = 0
    seen_parents: set[str] = set()
    index = 0

    for hit in hits:
        if hit.parent_id in seen_parents:
            continue
        seen_parents.add(hit.parent_id)
        index += 1
        block = _format_context_block_v2(index, hit)
        if used + len(block) > LLM_MAX_CONTEXT_CHARS:
            break
        context_parts.append(block)
        used += len(block)

    context = (
        "\n".join(context_parts) if context_parts else "(no context retrieved)"
    )
    system = RAG_V2_SYSTEM_PROMPT + _answer_language_instruction(answer_language)
    user = (
        "Context excerpts:\n\n"
        f"{context}\n\n"
        f"Question: {question}\n\n"
        "Write your answer (2–4 sentences, cite [n], plain prose only)."
    )
    return system, user


def build_llm_only_messages_v2(
    question: str,
    *,
    answer_language: str | None = None,
) -> tuple[str, str]:
    system = LLM_ONLY_SYSTEM_PROMPT + _answer_language_instruction(answer_language)
    user = f"Question: {question}"
    return system, user


__all__ = [
    "IDK_ANSWER",
    "LLMError",
    "build_llm_only_messages_v2",
    "build_rag_messages_v2",
    "generate_chat",
    "hits_to_sources_v2",
]
