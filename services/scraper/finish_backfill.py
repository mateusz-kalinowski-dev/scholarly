"""
Wymuś koniec backfillu i przełącz scraper na incremental (nowe prace od góry API).

Użycie:
  docker compose run --rm scraper python finish_backfill.py
  docker compose restart scraper
"""
import sys

import redis

from config import (
    BACKFILL_CURSOR_KEY,
    BACKFILL_DONE_KEY,
    CHECKPOINT_KEY,
    INCREMENTAL_CURSOR_KEY,
    REDIS_URL,
)

r = redis.from_url(REDIS_URL, decode_responses=True)


def main() -> int:
    cursor = r.get(BACKFILL_CURSOR_KEY)
    checkpoint = r.get(CHECKPOINT_KEY)
    r.set(BACKFILL_DONE_KEY, "1")
    r.delete(BACKFILL_CURSOR_KEY)
    r.delete(INCREMENTAL_CURSOR_KEY)
    print("backfill_done=1, usunięto kursor backfill i incremental")
    print(f"  poprzedni kursor backfill: {cursor or 'brak'}")
    print(f"  checkpoint (zostaje):      {checkpoint or 'brak'}")
    print("\nScraper przy następnym cyklu pobierze NOWE prace (start=0, incremental).")
    print("  docker compose restart scraper")
    return 0


if __name__ == "__main__":
    sys.exit(main())
