"""Embeddingi Ollama — batch przez /api/embed, fallback na /api/embeddings."""
from __future__ import annotations

import logging
import time

import redis
import requests

from config import (
    EMBED_BATCH_SIZE,
    EMBED_MAX_CHARS,
    EMBED_MODEL,
    EMBED_REQUEST_TIMEOUT,
    IVFFLAT_COUNTER_KEY,
    IVFFLAT_INDEX_EVERY_N_PAPERS,
    IVFFLAT_MIN_CHUNKS,
    OLLAMA_URL,
    POSTGRES_URL,
    REDIS_URL,
)
from psycopg import connect

logger = logging.getLogger(__name__)


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


def _trim(text: str) -> str:
    return text[:EMBED_MAX_CHARS] if text else ""


def _embed_api_batch(texts: list[str]) -> list[list[float]] | None:
    """Ollama POST /api/embed — wiele tekstów w jednym żądaniu."""
    if not texts:
        return []

    response = requests.post(
        f"{OLLAMA_URL}/api/embed",
        json={"model": EMBED_MODEL, "input": texts},
        timeout=EMBED_REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        logger.warning(
            "api/embed HTTP %s: %s",
            response.status_code,
            response.text[:200],
        )
        return None

    data = response.json()
    embeddings = data.get("embeddings")
    if not embeddings or len(embeddings) != len(texts):
        logger.warning(
            "api/embed: oczekiwano %d wektorów, jest %s",
            len(texts),
            len(embeddings) if embeddings else 0,
        )
        return None
    return embeddings


def get_embedding(text: str) -> list[float] | None:
    """Pojedynczy wektor — stary endpoint (fallback)."""
    if not text or not text.strip():
        return None

    response = requests.post(
        f"{OLLAMA_URL}/api/embeddings",
        json={"model": EMBED_MODEL, "prompt": _trim(text)},
        timeout=EMBED_REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        return None
    return response.json().get("embedding")


def embed_texts(texts: list[str]) -> list[list[float] | None]:
    """
    Embeddingi dla listy tekstów — batchami po EMBED_BATCH_SIZE.
    Zwraca listę tej samej długości co texts (None = błąd / pusty tekst).
    """
    results: list[list[float] | None] = [None] * len(texts)
    work: list[tuple[int, str]] = []

    for i, raw in enumerate(texts):
        if raw and raw.strip():
            work.append((i, _trim(raw)))

    if not work:
        return results

    for offset in range(0, len(work), EMBED_BATCH_SIZE):
        batch = work[offset : offset + EMBED_BATCH_SIZE]
        indices = [i for i, _ in batch]
        batch_texts = [t for _, t in batch]

        logger.info(
            "Embedding batch %d–%d / %d tekstów",
            offset + 1,
            offset + len(batch),
            len(work),
        )

        embeddings = _embed_api_batch(batch_texts)
        if embeddings is None:
            logger.info("Fallback: pojedyncze /api/embeddings dla batcha")
            for idx, text in zip(indices, batch_texts, strict=True):
                results[idx] = get_embedding(text)
            continue

        for idx, emb in zip(indices, embeddings, strict=True):
            results[idx] = emb

    return results


_redis = redis.from_url(REDIS_URL, decode_responses=True)


def _maintain_ivfflat_index(conn) -> None:
    """CREATE (pierwszy raz) lub REINDEX po zebraniu partii embeddingów."""
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL")
        chunk_count = cur.fetchone()[0]
        if chunk_count < IVFFLAT_MIN_CHUNKS:
            logger.info(
                "IVFFlat: za mało chunków (%s < %s), pomijam",
                chunk_count,
                IVFFLAT_MIN_CHUNKS,
            )
            return

        cur.execute(
            "SELECT 1 FROM pg_indexes WHERE indexname = 'chunks_embedding_idx'"
        )
        index_exists = cur.fetchone() is not None

    try:
        with conn.cursor() as cur:
            if not index_exists:
                logger.info(
                    "IVFFlat: tworzenie indeksu (%s chunków)...", chunk_count
                )
                cur.execute(
                    """
                    CREATE INDEX chunks_embedding_idx ON chunks
                    USING ivfflat (embedding vector_cosine_ops)
                    WITH (lists = 100)
                    """
                )
            else:
                logger.info(
                    "IVFFlat: REINDEX (%s chunków, co %s prac)...",
                    chunk_count,
                    IVFFLAT_INDEX_EVERY_N_PAPERS,
                )
                cur.execute("REINDEX INDEX chunks_embedding_idx")
            conn.commit()
        logger.info("IVFFlat: indeks gotowy")
    except Exception as e:
        conn.rollback()
        logger.warning("IVFFlat nieudany: %s", e)


def maybe_refresh_ivfflat_index() -> None:
    """Wywołaj po ukończeniu papera — indeks co IVFFLAT_INDEX_EVERY_N_PAPERS."""
    count = _redis.incr(IVFFLAT_COUNTER_KEY)
    if count < IVFFLAT_INDEX_EVERY_N_PAPERS:
        logger.debug(
            "IVFFlat: %s/%s prac od ostatniego indeksu",
            count,
            IVFFLAT_INDEX_EVERY_N_PAPERS,
        )
        return

    _redis.set(IVFFLAT_COUNTER_KEY, 0)
    logger.info(
        "IVFFlat: próg %s prac — odświeżam indeks",
        IVFFLAT_INDEX_EVERY_N_PAPERS,
    )
    with connect(POSTGRES_URL) as conn:
        _maintain_ivfflat_index(conn)
