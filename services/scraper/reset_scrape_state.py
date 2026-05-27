"""
Reset scrapera — ponowny backfill miesiąca.

Użycie (zalecane przed szybkim zrzutem):
  docker compose run --rm scraper python reset_scrape_state.py

Opcjonalnie usuń też Redis seen (nie jest potrzebne — dedup jest w Postgres):
  docker compose run --rm scraper python reset_scrape_state.py --full
"""
import argparse
import sys

import redis

from config import (
    BACKFILL_CURSOR_KEY,
    BACKFILL_DONE_KEY,
    CHECKPOINT_KEY,
    INCREMENTAL_CURSOR_KEY,
    INITIAL_LOOKBACK_DAYS,
    REDIS_URL,
    SEEN_IDS_KEY,
)

r = redis.from_url(REDIS_URL, decode_responses=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--full",
        action="store_true",
        help="Usuń też scraper:seen_arxiv_ids (opcjonalnie)",
    )
    args = parser.parse_args()

    keys = [
        CHECKPOINT_KEY,
        BACKFILL_DONE_KEY,
        BACKFILL_CURSOR_KEY,
        INCREMENTAL_CURSOR_KEY,
    ]
    if args.full:
        keys.append(SEEN_IDS_KEY)

    deleted = r.delete(*keys)
    print(f"Usunięto {deleted} kluczy Redis")
    print(f"Backfill od {INITIAL_LOOKBACK_DAYS} dni wstecz przy następnym starcie scrapera")
    print("Dedup po stronie processora: Postgres (embedding_status=DONE)")
    print("\nUruchom:")
    print("  docker compose up -d --build scraper processor processor-2 processor-3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
