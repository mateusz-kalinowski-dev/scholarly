import argparse
import logging
import sys
import time
from datetime import datetime, timezone

import pika
from pika.exceptions import AMQPError, StreamLostError

from arxiv_client import fetch_page
from arxiv_query import build_search_query
from config import ARXIV_PAGE_SIZE, RABBITMQ_URL
from dedup import seen_count
from scraper import entry_to_paper_data, publish_paper

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def parse_date(value: str) -> datetime:
    dt = datetime.strptime(value, "%Y-%m-%d")
    return dt.replace(tzinfo=timezone.utc)


def connect_channel():
    params = pika.URLParameters(RABBITMQ_URL)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.queue_declare(queue="paper_tasks", durable=True)
    return connection, channel


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill arXiv for date range")
    parser.add_argument("--from-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--to-date", required=True, help="YYYY-MM-DD")
    parser.add_argument("--max-pages", type=int, default=200)
    args = parser.parse_args()

    date_from = parse_date(args.from_date)
    date_to = parse_date(args.to_date)
    if date_to < date_from:
        raise ValueError("--to-date must be >= --from-date")

    query = build_search_query(date_from=date_from, date_to=date_to)

    connection, channel = connect_channel()

    start = 0
    pages = 0
    queued = 0
    scanned = 0

    logger.info(
        "Backfill range: %s -> %s, page_size=%s, seen_redis=%s",
        args.from_date,
        args.to_date,
        ARXIV_PAGE_SIZE,
        seen_count(),
    )

    while pages < args.max_pages:
        feed = fetch_page(query, start=start, max_results=ARXIV_PAGE_SIZE)
        if not feed or not feed.entries:
            break

        for entry in feed.entries:
            scanned += 1
            for attempt in range(3):
                try:
                    if publish_paper(channel, entry_to_paper_data(entry)):
                        queued += 1
                    break
                except (StreamLostError, AMQPError) as exc:
                    logger.warning(
                        "RabbitMQ publish error (attempt %s/3): %s",
                        attempt + 1,
                        exc,
                    )
                    try:
                        connection.close()
                    except Exception:
                        pass
                    time.sleep(2)
                    connection, channel = connect_channel()
            else:
                raise RuntimeError("Nie udało się opublikować wiadomości po 3 próbach")

        pages += 1
        if len(feed.entries) < ARXIV_PAGE_SIZE:
            break
        start += ARXIV_PAGE_SIZE

    connection.close()
    logger.info(
        "Backfill range DONE: scanned=%s queued=%s pages=%s",
        scanned,
        queued,
        pages,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
