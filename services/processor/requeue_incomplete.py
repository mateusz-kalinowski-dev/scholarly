"""
Ponowne wrzucenie na kolejkę prac bez embedding_status=DONE (z Postgres).

Użycie:
  docker compose run --rm processor python requeue_incomplete.py
  docker compose run --rm processor python requeue_incomplete.py --include-failed
  docker compose run --rm processor python requeue_incomplete.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

import pika
from psycopg import connect

from config import POSTGRES_URL, RABBITMQ_URL

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def fetch_incomplete(include_failed: bool) -> list[dict]:
    if include_failed:
        where = "embedding_status IS DISTINCT FROM 'DONE'"
    else:
        where = "embedding_status IN ('PENDING') OR embedding_status IS NULL"

    sql = f"""
        SELECT
            arxiv_id, title, summary, arxiv_url, pdf_url,
            published_at::text, updated_at::text,
            primary_category, categories, authors
        FROM papers
        WHERE {where}
        ORDER BY created_at
    """
    rows: list[dict] = []
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            for row in cur.fetchall():
                arxiv_url = row[3] or f"https://arxiv.org/abs/{row[0]}"
                rows.append(
                    {
                        "id": row[0],
                        "title": row[1],
                        "summary_raw": row[2],
                        "arxiv_url": arxiv_url,
                        "pdf_url": row[4] or arxiv_url.replace("/abs/", "/pdf/"),
                        "source_url": arxiv_url.replace("/abs/", "/e-print/"),
                        "published": row[5],
                        "updated": row[6] or row[5],
                        "primary_category": row[7],
                        "categories": list(row[8] or []),
                        "authors": list(row[9] or []),
                    }
                )
    return rows


def publish_all(papers: list[dict]) -> int:
    params = pika.URLParameters(RABBITMQ_URL)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.queue_declare(queue="paper_tasks", durable=True)

    for paper in papers:
        channel.basic_publish(
            exchange="",
            routing_key="paper_tasks",
            body=json.dumps(paper),
            properties=pika.BasicProperties(delivery_mode=2),
        )

    connection.close()
    return len(papers)


def main() -> int:
    parser = argparse.ArgumentParser(description="Requeue incomplete papers from Postgres")
    parser.add_argument(
        "--include-failed",
        action="store_true",
        help="Uwzględnij też FAILED (domyślnie tylko PENDING)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Tylko policz, bez publish")
    args = parser.parse_args()

    papers = fetch_incomplete(args.include_failed)
    logger.info("Znaleziono %d prac do ponownej kolejki", len(papers))

    if args.dry_run:
        for p in papers[:10]:
            logger.info("  - %s", p["id"])
        if len(papers) > 10:
            logger.info("  ... i %d więcej", len(papers) - 10)
        return 0

    if not papers:
        return 0

    n = publish_all(papers)
    logger.info("Wysłano %d wiadomości na paper_tasks", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
