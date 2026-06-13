"""Tłumaczenie fragmentów źródeł na język użytkownika (tylko tryb rewrite)."""
from __future__ import annotations

import json
import logging
import re

from app.schemas import SearchHit, SourceChunk
from app.services.rag import LLMError, generate_answer

logger = logging.getLogger(__name__)

_EN_LANGUAGES = frozenset({"english", "en", "angielski"})


def _needs_translation(user_language: str) -> bool:
    return user_language.strip().lower() not in _EN_LANGUAGES


async def translate_source_chunks(
    sources: list[SourceChunk],
    user_language: str,
) -> list[SourceChunk]:
    if not sources or not _needs_translation(user_language):
        return sources

    numbered = "\n\n".join(
        f"[{i + 1}]\n{src.content[:600]}"
        for i, src in enumerate(sources)
    )
    prompt = (
        f"Translate each numbered excerpt to {user_language}. "
        "Keep technical terms accurate. Output ONLY JSON array:\n"
        '[{{"index": 1, "translation": "..."}}, ...]\n\n'
        f"EXCERPTS:\n{numbered}"
    )

    try:
        raw = await generate_answer(prompt)
    except LLMError:
        logger.warning("Tłumaczenie źródeł nieudane — zostawiam oryginał")
        return sources

    match = re.search(r"\[[\s\S]*\]", raw.strip())
    if not match:
        return sources

    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return sources

    by_index: dict[int, str] = {}
    for item in items:
        if isinstance(item, dict) and "index" in item and "translation" in item:
            by_index[int(item["index"])] = str(item["translation"]).strip()

    updated: list[SourceChunk] = []
    for i, src in enumerate(sources):
        translation = by_index.get(i + 1)
        if translation:
            updated.append(
                src.model_copy(
                    update={
                        "content": translation,
                        "content_original": src.content,
                    }
                )
            )
        else:
            updated.append(src)
    return updated


async def translate_search_hits(
    hits: list[SearchHit],
    user_language: str,
) -> list[SearchHit]:
    if not hits or not _needs_translation(user_language):
        return hits

    numbered = "\n\n".join(
        f"[{i + 1}]\n{h.content[:600]}" for i, h in enumerate(hits)
    )
    prompt = (
        f"Translate each numbered excerpt to {user_language}. "
        "Output ONLY JSON array:\n"
        '[{{"index": 1, "translation": "..."}}, ...]\n\n'
        f"EXCERPTS:\n{numbered}"
    )

    try:
        raw = await generate_answer(prompt)
    except LLMError:
        return hits

    match = re.search(r"\[[\s\S]*\]", raw.strip())
    if not match:
        return hits

    try:
        items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return hits

    by_index: dict[int, str] = {}
    for item in items:
        if isinstance(item, dict) and "index" in item and "translation" in item:
            by_index[int(item["index"])] = str(item["translation"]).strip()

    updated: list[SearchHit] = []
    for i, hit in enumerate(hits):
        translation = by_index.get(i + 1)
        if translation:
            updated.append(
                hit.model_copy(
                    update={
                        "content": translation,
                        "content_original": hit.content,
                    }
                )
            )
        else:
            updated.append(hit)
    return updated
