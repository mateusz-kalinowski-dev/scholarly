"""Dedup: pomijaj DONE oraz trwały brak źródła (parsing FAILED)."""
from __future__ import annotations

import logging

import redis
from psycopg import connect

from arxiv_ids import normalize_arxiv_id
from config import POSTGRES_URL, REDIS_URL, SEEN_IDS_KEY

logger = logging.getLogger(__name__)

r_client = redis.from_url(REDIS_URL, decode_responses=True)


def postgres_paper_status(arxiv_id: str) -> tuple[str | None, str | None]:
    base_id = normalize_arxiv_id(arxiv_id)
    try:
        with connect(POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT embedding_status, parsing_status
                    FROM papers WHERE arxiv_id = %s
                    """,
                    (base_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None, None
                return row[0], row[1]
    except Exception as e:
        logger.warning("Postgres niedostępny przy dedup (%s) — nie pomijam", e)
        return None, None


def should_skip_publish(arxiv_id: str) -> bool:
    """
    True = nie wrzucaj na kolejkę.
    DONE lub trwały brak źródła (parsing FAILED).
    """
    embedding_status, parsing_status = postgres_paper_status(arxiv_id)
    if embedding_status == "DONE":
        return True
    if parsing_status == "FAILED":
        return True
    return False


def mark_queued(arxiv_id: str) -> None:
    """Statystyka w Redis (nie blokuje ponownego wysłania)."""
    r_client.sadd(SEEN_IDS_KEY, normalize_arxiv_id(arxiv_id))


def seen_count() -> int:
    return r_client.scard(SEEN_IDS_KEY) or 0
