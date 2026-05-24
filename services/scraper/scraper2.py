import json
import logging
import time
from datetime import datetime, timedelta, timezone

import pika
import redis

from arxiv_client import fetch_page
from arxiv_ids import normalize_arxiv_id
from arxiv_query import build_search_query
from config import (
    ARXIV_MAX_PAGES_PER_RUN,
    ARXIV_PAGE_SIZE,
    BACKFILL_CURSOR_KEY,
    BACKFILL_DONE_KEY,
    CHECKPOINT_KEY,
    INITIAL_LOOKBACK_DAYS,
    RABBITMQ_URL,
    REDIS_URL,
    SCRAPER_INTERVAL_SECONDS,
)
from dedup import is_seen, mark_seen, seen_count

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

r_client = redis.from_url(REDIS_URL, decode_responses=True)


def connect_rabbitmq():
    while True:
        try:
            params = pika.URLParameters(RABBITMQ_URL)
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            channel.queue_declare(queue="paper_tasks", durable=True)
            return connection, channel
        except Exception as pika_err:
            logger.warning("RabbitMQ: %s — ponawiam za 5s", pika_err)
            time.sleep(5)


def entry_to_paper_data(entry) -> dict:
    raw_id = entry.id.split("/")[-1]
    arxiv_id = normalize_arxiv_id(raw_id)
    arxiv_url = entry.link
    return {
        "id": arxiv_id,
        "title": entry.title.replace("\n", " "),
        "authors": [a.name for a in entry.authors],
        "arxiv_url": arxiv_url,
        "pdf_url": arxiv_url.replace("/abs/", "/pdf/"),
        "source_url": arxiv_url.replace("/abs/", "/e-print/"),
        "published": entry.published,
        "updated": entry.get("updated", entry.published),
        "primary_category": (
            entry.arxiv_primary_category["term"]
            if "arxiv_primary_category" in entry
            else None
        ),
        "categories": [tag["term"] for tag in entry.get("tags", [])],
        "summary_raw": entry.summary,
    }


def parse_published(published_str: str) -> datetime:
    clean_str = published_str.replace("Z", "+00:00")
    dt = datetime.fromisoformat(clean_str)
    
    # Upewniamy się, że data ma przypisaną strefę czasową (tzinfo)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
        
    return dt


def publish_paper(channel, paper_data: dict) -> bool:
    arxiv_id = paper_data["id"]
    if is_seen(arxiv_id):
        return False

    channel.basic_publish(
        exchange="",
        routing_key="paper_tasks",
        body=json.dumps(paper_data),
        properties=pika.BasicProperties(delivery_mode=2),
    )
    mark_seen(arxiv_id)
    logger.info("Kolejka: %s — %s", arxiv_id, paper_data["title"][:60])
    return True


def run_backfill(channel, cutoff: datetime) -> int:
    """Paginacja wstecz do cutoff (miesiąc). Zwraca liczbę nowych wpisów w kolejce."""
    date_to = datetime.now(timezone.utc)
    query = build_search_query(date_from=cutoff, date_to=date_to)
    start = int(r_client.get(BACKFILL_CURSOR_KEY) or 0)
    queued = 0
    pages = 0
    newest_timestamp = r_client.get(CHECKPOINT_KEY)

    logger.info(
        "Backfill CS (40 kat.) od %s, start=%s, dedup w Redis: %d id",
        cutoff.date(),
        start,
        seen_count(),
    )

    while pages < ARXIV_MAX_PAGES_PER_RUN:
        feed = fetch_page(query, start=start, max_results=ARXIV_PAGE_SIZE)
        if not feed or not feed.entries:
            logger.info("Backfill: brak wyników na start=%s — koniec", start)
            r_client.set(BACKFILL_DONE_KEY, "1")
            r_client.delete(BACKFILL_CURSOR_KEY)
            break

        reached_cutoff = False
        for entry in feed.entries:
            published_dt = parse_published(entry.published)
            if published_dt < cutoff:
                reached_cutoff = True
                break
            if publish_paper(channel, entry_to_paper_data(entry)):
                queued += 1
            pub = entry.published
            if newest_timestamp is None or pub > newest_timestamp:
                newest_timestamp = pub

        if reached_cutoff:
            logger.info("Backfill: osiągnięto cutoff %s", cutoff.date())
            r_client.set(BACKFILL_DONE_KEY, "1")
            r_client.delete(BACKFILL_CURSOR_KEY)
            break

        if len(feed.entries) < ARXIV_PAGE_SIZE:
            logger.info("Backfill: ostatnia strona wyników")
            r_client.set(BACKFILL_DONE_KEY, "1")
            r_client.delete(BACKFILL_CURSOR_KEY)
            break

        start += ARXIV_PAGE_SIZE
        r_client.set(BACKFILL_CURSOR_KEY, str(start))
        pages += 1

    if newest_timestamp:
        r_client.set(CHECKPOINT_KEY, newest_timestamp)

    return queued


def run_incremental(channel, last_checkpoint: str | None) -> int:
    """Nowe prace od ostatniego checkpointu (sort desc, stop gdy <= checkpoint)."""
    query = build_search_query()
    queued = 0

    logger.info("Tryb incremental, checkpoint=%s", last_checkpoint)

    feed = fetch_page(query, start=0, max_results=ARXIV_PAGE_SIZE)
    if not feed or not feed.entries:
        return 0

    newest_timestamp: str | None = None

    for entry in feed.entries:
        published_time = entry.published
        if last_checkpoint and published_time <= last_checkpoint:
            break

        if publish_paper(channel, entry_to_paper_data(entry)):
            queued += 1
        if newest_timestamp is None or published_time > newest_timestamp:
            newest_timestamp = published_time

    if newest_timestamp:
        r_client.set(CHECKPOINT_KEY, newest_timestamp)
        logger.info("Checkpoint -> %s", newest_timestamp)

    return queued


def run_scraper():
    logger.info("Scraper arXiv — 40 kategorii CS")
    connection, channel = connect_rabbitmq()

    while True:
        backfill_done = r_client.get(BACKFILL_DONE_KEY) == "1"
        last_checkpoint = r_client.get(CHECKPOINT_KEY)
        queued = 0

        if not backfill_done:
            cutoff = datetime.now(timezone.utc) - timedelta(days=INITIAL_LOOKBACK_DAYS)
            queued = run_backfill(channel, cutoff)
        else:
            queued = run_incremental(channel, last_checkpoint)

        logger.info(
            "Cykl zakończony — do kolejki: %d, backfill_done=%s, sleep=%ss",
            queued,
            r_client.get(BACKFILL_DONE_KEY) == "1",
            SCRAPER_INTERVAL_SECONDS,
        )
        time.sleep(SCRAPER_INTERVAL_SECONDS)


if __name__ == "__main__":
    run_scraper()
