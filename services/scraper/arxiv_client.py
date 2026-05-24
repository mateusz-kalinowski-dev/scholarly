import logging
import time

import feedparser
import requests

from config import (
    ARXIV_MAX_RETRIES,
    ARXIV_REQUEST_DELAY,
    ARXIV_USER_AGENT,
)

logger = logging.getLogger(__name__)

ARXIV_API = "http://export.arxiv.org/api/query?"


def fetch_page(
    search_query: str,
    *,
    start: int = 0,
    max_results: int = 200,
) -> feedparser.FeedParserDict | None:
    safe_query = search_query.replace(" ", "+")
    url = (
        f"{ARXIV_API}search_query={safe_query}"
        f"&sortBy=submittedDate&sortOrder=descending"
        f"&start={start}&max_results={max_results}"
    )

    headers = {"User-Agent": ARXIV_USER_AGENT}
    base_delay = ARXIV_REQUEST_DELAY

    for attempt in range(ARXIV_MAX_RETRIES):
        try:
            logger.info(
                "arXiv API start=%s max=%s (próba %s)",
                start,
                max_results,
                attempt + 1,
            )
            response = requests.get(url, headers=headers, timeout=60)

            if response.status_code == 200:
                time.sleep(ARXIV_REQUEST_DELAY)
                return feedparser.parse(response.content)

            delay = base_delay * (2**attempt)
            logger.warning("arXiv HTTP %s — czekam %ss", response.status_code, delay)
            time.sleep(delay)
        except requests.RequestException as exc:
            delay = base_delay * (2**attempt)
            logger.error("arXiv sieć: %s — czekam %ss", exc, delay)
            time.sleep(delay)

    return None
