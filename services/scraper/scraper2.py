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
    CHECKPOINT_COMMIT_EVERY,
    CHECKPOINT_KEY,
    INCREMENTAL_CURSOR_KEY,
    INITIAL_LOOKBACK_DAYS,
    RABBITMQ_URL,
    REDIS_URL,
    SCRAPER_INTERVAL_SECONDS,
    SCRAPER_RESET_ON_START,
)
from dedup import mark_queued, should_skip_publish

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


def reset_for_month_backfill() -> None:
    """Czyści checkpoint i kursory — backfill od INITIAL_LOOKBACK_DAYS."""
    deleted = r_client.delete(
        CHECKPOINT_KEY,
        BACKFILL_DONE_KEY,
        BACKFILL_CURSOR_KEY,
        INCREMENTAL_CURSOR_KEY,
    )
    logger.info(
        "Reset stanu scrapera (%s kluczy) — backfill od %s dni wstecz",
        deleted,
        INITIAL_LOOKBACK_DAYS,
    )


class CheckpointTracker:
    """Zapisuje timestamp najnowszej przeczytanej pozycji co N wpisów i na końcu cyklu."""

    def __init__(self) -> None:
        self.newest: str | None = r_client.get(CHECKPOINT_KEY)
        self._since_commit = 0

    def note(self, published: str) -> None:
        self._since_commit += 1
        if self.newest is None or published > self.newest:
            self.newest = published
        if self._since_commit >= CHECKPOINT_COMMIT_EVERY:
            self.flush()

    def flush(self) -> None:
        if self.newest:
            r_client.set(CHECKPOINT_KEY, self.newest)
            logger.info("Checkpoint -> %s", self.newest)
        self._since_commit = 0


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
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def publish_paper(channel, paper_data: dict) -> bool:
    arxiv_id = paper_data["id"]
    if should_skip_publish(arxiv_id):
        return False

    channel.basic_publish(
        exchange="",
        routing_key="paper_tasks",
        body=json.dumps(paper_data),
        properties=pika.BasicProperties(delivery_mode=2),
    )
    mark_queued(arxiv_id)
    logger.info("Kolejka: %s — %s", arxiv_id, paper_data["title"][:60])
    return True


def _page_limit() -> int:
    """0 = bez limitu stron na cykl (jeden długi backfill)."""
    if ARXIV_MAX_PAGES_PER_RUN <= 0:
        return 1_000_000
    return ARXIV_MAX_PAGES_PER_RUN


def run_backfill(channel, cutoff: datetime, tracker: CheckpointTracker) -> int:
    date_to = datetime.now(timezone.utc)
    query = build_search_query(date_from=cutoff, date_to=date_to)
    start = int(r_client.get(BACKFILL_CURSOR_KEY) or 0)
    queued = 0
    pages = 0
    page_cap = _page_limit()

    logger.info(
        "Backfill CS od %s, start=%s, max_pages/cykl=%s, commit co %s",
        cutoff.date(),
        start,
        "∞" if ARXIV_MAX_PAGES_PER_RUN <= 0 else ARXIV_MAX_PAGES_PER_RUN,
        CHECKPOINT_COMMIT_EVERY,
    )

    while pages < page_cap:
        feed = fetch_page(query, start=start, max_results=ARXIV_PAGE_SIZE)
        if not feed or not feed.entries:
            if feed is None:
                logger.warning(
                    "Backfill: błąd API start=%s — kursor bez zmian",
                    start,
                )
                break
            logger.info("Backfill: koniec wyników na start=%s", start)
            r_client.set(BACKFILL_DONE_KEY, "1")
            r_client.delete(BACKFILL_CURSOR_KEY)
            break

        reached_cutoff = False
        for entry in feed.entries:
            published_dt = parse_published(entry.published)
            if published_dt < cutoff:
                reached_cutoff = True
                break
            tracker.note(entry.published)
            if publish_paper(channel, entry_to_paper_data(entry)):
                queued += 1

        if reached_cutoff:
            logger.info("Backfill: cutoff %s osiągnięty", cutoff.date())
            r_client.set(BACKFILL_DONE_KEY, "1")
            r_client.delete(BACKFILL_CURSOR_KEY)
            break

        if len(feed.entries) < ARXIV_PAGE_SIZE:
            logger.info("Backfill: ostatnia strona API")
            r_client.set(BACKFILL_DONE_KEY, "1")
            r_client.delete(BACKFILL_CURSOR_KEY)
            break

        start += ARXIV_PAGE_SIZE
        r_client.set(BACKFILL_CURSOR_KEY, str(start))
        pages += 1

    return queued


def run_incremental(channel, last_checkpoint: str | None, tracker: CheckpointTracker) -> int:
    query = build_search_query()
    queued = 0
    pages = 0
    start = int(r_client.get(INCREMENTAL_CURSOR_KEY) or 0)
    page_cap = _page_limit()

    logger.info(
        "Incremental, checkpoint=%s, start=%s",
        last_checkpoint,
        start,
    )

    while pages < page_cap:
        feed = fetch_page(query, start=start, max_results=ARXIV_PAGE_SIZE)
        if not feed or not feed.entries:
            if feed is None:
                logger.warning("Incremental: błąd API start=%s", start)
                break
            r_client.delete(INCREMENTAL_CURSOR_KEY)
            break

        reached_checkpoint = False
        for entry in feed.entries:
            published_time = entry.published
            # Tylko ściśle starsze niż checkpoint; duplikaty odcina Postgres (DONE)
            if last_checkpoint and published_time < last_checkpoint:
                reached_checkpoint = True
                break

            tracker.note(published_time)
            if publish_paper(channel, entry_to_paper_data(entry)):
                queued += 1

        if reached_checkpoint:
            r_client.delete(INCREMENTAL_CURSOR_KEY)
            break

        if len(feed.entries) < ARXIV_PAGE_SIZE:
            r_client.delete(INCREMENTAL_CURSOR_KEY)
            break

        start += ARXIV_PAGE_SIZE
        r_client.set(INCREMENTAL_CURSOR_KEY, str(start))
        pages += 1

    return queued


def run_scraper():
    logger.info(
        "Scraper arXiv — %d kat. CS, sleep po cyklu=%ss, commit co %s",
        40,
        SCRAPER_INTERVAL_SECONDS,
        CHECKPOINT_COMMIT_EVERY,
    )

    if SCRAPER_RESET_ON_START:
        reset_for_month_backfill()

    connection, channel = connect_rabbitmq()
    tracker = CheckpointTracker()

    while True:
        backfill_done = r_client.get(BACKFILL_DONE_KEY) == "1"
        last_checkpoint = r_client.get(CHECKPOINT_KEY)
        tracker.newest = last_checkpoint
        tracker._since_commit = 0

        if not backfill_done:
            cutoff = datetime.now(timezone.utc) - timedelta(days=INITIAL_LOOKBACK_DAYS)
            queued = run_backfill(channel, cutoff, tracker)
        else:
            queued = run_incremental(channel, last_checkpoint, tracker)

        tracker.flush()

        logger.info(
            "Cykl zakończony — kolejka +%d, backfill_done=%s, sleep %ss",
            queued,
            r_client.get(BACKFILL_DONE_KEY) == "1",
            SCRAPER_INTERVAL_SECONDS,
        )
        time.sleep(SCRAPER_INTERVAL_SECONDS)


if __name__ == "__main__":
    run_scraper()
