"""Embeddingi tekstu (Ollama)."""
from __future__ import annotations

import asyncio
import logging
import math
import re

import httpx

from app.config import (
    EMBED_DIM,
    EMBED_MAX_CHARS,
    EMBED_MODEL,
    OLLAMA_BASE_URL,
)
from app.services.ollama_client import recover_embed_after_nan

logger = logging.getLogger(__name__)

_embed_lock = asyncio.Lock()
_EMBED_MAX_RETRIES = 3

# Ollama bge-m3 zwraca NaN dla niektórych fraz (np. "corresponding levels of support based on…")
_EMBED_PHRASE_FIXES: tuple[tuple[str, str], ...] = (
    (r"\bcorresponding levels of support based on evaluation results\b", "support levels from evaluation results"),
    (r"\bcorresponding levels of\b", ""),
)


class EmbeddingError(Exception):
    pass


def to_vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(v) for v in values) + "]"


def _normalize_embed_text(text: str) -> str:
    out = text.strip()
    for pattern, replacement in _EMBED_PHRASE_FIXES:
        out = re.sub(pattern, replacement, out, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", out).strip()


def _embed_text_variants(text: str) -> list[str]:
    """Kolejne warianty zapytania do embed (fallback przy NaN z Ollama)."""
    seen: set[str] = set()
    variants: list[str] = []

    def add(candidate: str) -> None:
        cleaned = _normalize_embed_text(candidate)
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            variants.append(cleaned)

    add(text)
    words = text.split()
    if len(words) > 12:
        add(" ".join(words[:12]))
    if len(words) > 6:
        add(" ".join(words[:6]))
    return variants


def _vector_valid(vec: list[float]) -> bool:
    return bool(vec) and not any(math.isnan(v) or math.isinf(v) for v in vec)


async def _embed_with_model(
    text: str,
    model: str,
    expected_dim: int | None,
    *,
    extra_candidates: list[str] | None = None,
) -> list[float]:
    if not text.strip():
        raise EmbeddingError("Pusty tekst do embeddingu")

    last_error = "nieznany błąd"
    candidates = _embed_text_variants(text[:EMBED_MAX_CHARS])
    if extra_candidates:
        seen = set(candidates)
        for fb in extra_candidates:
            for variant in _embed_text_variants(fb):
                if variant not in seen:
                    seen.add(variant)
                    candidates.append(variant)

    async with _embed_lock:
        for candidate in candidates:
            for attempt in range(_EMBED_MAX_RETRIES):
                async with httpx.AsyncClient(timeout=120.0) as client:
                    response = await client.post(
                        f"{OLLAMA_BASE_URL}/api/embed",
                        json={"model": model, "input": candidate},
                    )

                if response.status_code != 200:
                    last_error = (
                        f"Ollama embed HTTP {response.status_code}: {response.text[:200]}"
                    )
                    is_nan = "NaN" in response.text
                    if is_nan and attempt < _EMBED_MAX_RETRIES - 1:
                        logger.warning(
                            "Embed NaN dla %r (próba %d/%d), retry…",
                            candidate[:60],
                            attempt + 1,
                            _EMBED_MAX_RETRIES,
                        )
                        await recover_embed_after_nan()
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    if is_nan:
                        break
                    raise EmbeddingError(last_error)

                data = response.json()
                embeddings = data.get("embeddings")
                if embeddings and len(embeddings) == 1:
                    vec = embeddings[0]
                else:
                    vec = data.get("embedding")
                if not vec:
                    raise EmbeddingError("Brak wektora w odpowiedzi Ollama")
                if not _vector_valid(vec):
                    last_error = f"Nieprawidłowy wektor (NaN/Inf), model={model}"
                    if attempt < _EMBED_MAX_RETRIES - 1:
                        await recover_embed_after_nan()
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    break
                if expected_dim and len(vec) != expected_dim:
                    raise EmbeddingError(
                        f"Nieoczekiwany wymiar {len(vec)} (oczekiwano {expected_dim}, model={model})"
                    )
                if candidate != text.strip():
                    logger.info(
                        "Embed fallback: użyto skróconego zapytania (%d znaków)",
                        len(candidate),
                    )
                return vec

    raise EmbeddingError(last_error)


async def embed_text(text: str, *, fallbacks: list[str] | None = None) -> list[float]:
    return await _embed_with_model(
        text,
        EMBED_MODEL,
        expected_dim=EMBED_DIM,
        extra_candidates=fallbacks,
    )
