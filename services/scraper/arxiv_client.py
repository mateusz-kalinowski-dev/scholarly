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

ARXIV_API = "https://export.arxiv.org/api/query?"


def _retry_delay(response: requests.Response | None, attempt: int, base: float) -> float:
    if response is not None:
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.isdigit():
            return max(float(retry_after), base)
        if response.status_code in (429, 503):
            return max(base * (3**attempt), 30.0)
    return base * (2**attempt)


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
    response: requests.Response | None = None

    for attempt in range(ARXIV_MAX_RETRIES):
        try:
            logger.info(
                "arXiv API start=%s max=%s (próba %s)",
                start,
                max_results,
                attempt + 1,
            )
            response = requests.get(url, headers=headers, timeout=90)

            if response.status_code == 200:
                time.sleep(ARXIV_REQUEST_DELAY)
                return feedparser.parse(response.content)

            delay = _retry_delay(response, attempt, base_delay)
            logger.warning(
                "arXiv HTTP %s — czekam %ss (start=%s)",
                response.status_code,
                delay,
                start,
            )
            time.sleep(delay)
        except requests.RequestException as exc:
            delay = _retry_delay(response, attempt, base_delay)
            logger.error("arXiv sieć: %s — czekam %ss", exc, delay)
            time.sleep(delay)

    logger.error("arXiv: wyczerpano próby dla start=%s — NIE przesuwam kursora", start)
    return None
