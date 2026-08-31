#!/usr/bin/env python3
"""
Odśwież text_search + przebuduj indeksy HNSW / GIN / BM25.

  python rebuild_indexes.py
  python rebuild_indexes.py --skip-refresh
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from dotenv import load_dotenv

load_dotenv()

from pipeline.db import rebuild_search_indexes, refresh_child_text_search

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("rebuild_indexes")


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild indeksów wyszukiwania")
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Pomiń odświeżenie text_search (już z triggera)",
    )
    args = parser.parse_args()

    if not args.skip_refresh:
        logger.info("Odświeżanie search_text / text_search (child)...")
        t0 = time.perf_counter()
        n = refresh_child_text_search()
        logger.info("Odświeżono %d child w %.0fs", n, time.perf_counter() - t0)

    logger.info("Przebudowa indeksów HNSW + GIN + BM25...")
    t0 = time.perf_counter()
    rebuild_search_indexes()
    logger.info("Indeksy gotowe w %.0fs", time.perf_counter() - t0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
