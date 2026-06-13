"""Przepisanie pytania użytkownika pod retrieval (EN) + wykrycie języka odpowiedzi."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from app.services.rag import LLMError, generate_answer

logger = logging.getLogger(__name__)

REWRITE_PROMPT = """You prepare search queries for an English scientific paper database (arXiv CS).

Given the USER MESSAGE below, output ONLY one JSON object (no markdown):
{{"retrieval_query": "<concise English search query, keywords, translate if needed>", "user_language": "<language name for the answer, e.g. Polish, English>"}}

Rules:
- retrieval_query: optimized for semantic search, not a full sentence to the user
- user_language: language the user wrote in (or clearly wants)

USER MESSAGE:
{question}
"""


@dataclass
class QueryRewriteResult:
    retrieval_query: str
    user_language: str
    original_question: str


def _parse_rewrite_json(raw: str, fallback_question: str) -> QueryRewriteResult:
    text = raw.strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    try:
        data = json.loads(text)
        retrieval = (data.get("retrieval_query") or "").strip()
        language = (data.get("user_language") or "").strip()
        if retrieval and language:
            return QueryRewriteResult(
                retrieval_query=retrieval,
                user_language=language,
                original_question=fallback_question,
            )
    except json.JSONDecodeError:
        logger.warning("Nie udało się sparsować JSON rewrite: %s", raw[:200])

    return QueryRewriteResult(
        retrieval_query=fallback_question,
        user_language="English",
        original_question=fallback_question,
    )


async def rewrite_query_for_retrieval(question: str) -> QueryRewriteResult:
    prompt = REWRITE_PROMPT.format(question=question)
    try:
        raw = await generate_answer(prompt)
    except LLMError:
        logger.exception("Rewrite query — fallback do oryginału")
        return QueryRewriteResult(
            retrieval_query=question,
            user_language="English",
            original_question=question,
        )
    return _parse_rewrite_json(raw, question)
