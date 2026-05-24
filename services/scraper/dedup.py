import logging

import redis

from arxiv_ids import normalize_arxiv_id
from config import REDIS_URL, SEEN_IDS_KEY

logger = logging.getLogger(__name__)

r_client = redis.from_url(REDIS_URL, decode_responses=True)


def is_seen(arxiv_id: str) -> bool:
    base_id = normalize_arxiv_id(arxiv_id)
    return bool(r_client.sismember(SEEN_IDS_KEY, base_id))


def mark_seen(arxiv_id: str) -> None:
    base_id = normalize_arxiv_id(arxiv_id)
    r_client.sadd(SEEN_IDS_KEY, base_id)


def seen_count() -> int:
    return r_client.scard(SEEN_IDS_KEY) or 0
