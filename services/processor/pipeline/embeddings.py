"""Embeddingi bge-m3 (1024d) przez Ollama."""
from __future__ import annotations

import logging
import math
import os
import time

import requests

from config import (
    EMBED_BATCH_SIZE,
    EMBED_DIM,
    EMBED_MAX_CHARS,
    EMBED_MODEL,
    EMBED_REQUEST_TIMEOUT,
    OLLAMA_URL,
)
from .sanitize import sanitize_embed_text

logger = logging.getLogger(__name__)

_EMBED_RETRIES = 3
_EMBED_BATCH_PAUSE = float(os.getenv("EMBED_BATCH_PAUSE", "0.05"))


def wait_for_ollama_models(models: list[str], host: str = OLLAMA_URL) -> None:
    logger.info("Czekam na Ollama i modele: %s", models)
    while True:
        try:
            response = requests.get(f"{host}/api/tags", timeout=5)
            if response.status_code == 200:
                available = [m["name"] for m in response.json().get("models", [])]
                missing = [m for m in models if not any(m in a for a in available)]
                if not missing:
                    logger.info("Modele gotowe: %s", models)
                    return
                logger.warning("Brakuje modeli: %s", missing)
            else:
                logger.warning("Ollama HTTP %s", response.status_code)
        except requests.RequestException:
            logger.warning("Brak połączenia z Ollamą...")
        time.sleep(10)


def _is_valid_embedding(emb: list[float] | None) -> bool:
    if not emb or len(emb) != EMBED_DIM:
        return False
    return all(math.isfinite(x) for x in emb)


def _post_embed(inputs: list[str]) -> list[list[float] | None]:
    if not inputs:
        return []
    response = requests.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": inputs},
        timeout=EMBED_REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        logger.warning(
            "embed HTTP %s: %s", response.status_code, response.text[:200]
        )
        return [None] * len(inputs)
    embeddings = response.json().get("embeddings") or []
    out: list[list[float] | None] = []
    for i in range(len(inputs)):
        emb = embeddings[i] if i < len(embeddings) else None
        out.append(emb if _is_valid_embedding(emb) else None)
    return out


def _embed_one(text: str) -> list[float] | None:
    clean = sanitize_embed_text(text, max_chars=EMBED_MAX_CHARS)
    limits = [EMBED_MAX_CHARS, EMBED_MAX_CHARS // 2, 2000, 500]
    for attempt, limit in enumerate(limits):
        payload = sanitize_embed_text(clean, max_chars=limit)
        for _ in range(_EMBED_RETRIES):
            result = _post_embed([payload])[0]
            if _is_valid_embedding(result):
                return result
            time.sleep(0.15 * (attempt + 1))
    return None


def embed_texts(texts: list[str]) -> list[list[float] | None]:
    if not texts:
        return []

    trimmed = [sanitize_embed_text(t, max_chars=EMBED_MAX_CHARS) for t in texts]
    out: list[list[float] | None] = [None] * len(trimmed)

    for start in range(0, len(trimmed), EMBED_BATCH_SIZE):
        batch = trimmed[start : start + EMBED_BATCH_SIZE]
        batch_result = _post_embed(batch)

        # Jeśli cały batch padł (np. przez toksyczny fragment), podziel go na mniejsze grupy
        # zamiast od razu odpalać kosztowny fallback per pojedynczy tekst.
        if len(batch) > 1 and all(v is None for v in batch_result):
            subgroup = max(1, min(8, len(batch) // 4 or 1))
            for offset in range(0, len(batch), subgroup):
                sub = batch[offset : offset + subgroup]
                sub_result = _post_embed(sub)
                for j, emb in enumerate(sub_result):
                    batch_result[offset + j] = emb

        if any(v is None for v in batch_result):
            for i, text in enumerate(batch):
                if batch_result[i] is None:
                    batch_result[i] = _embed_one(texts[start + i])

        for i, emb in enumerate(batch_result):
            out[start + i] = emb if _is_valid_embedding(emb) else None

        if _EMBED_BATCH_PAUSE > 0:
            time.sleep(_EMBED_BATCH_PAUSE)
    return out
