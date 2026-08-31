#!/usr/bin/env python3
"""
Backfill keywords + keywords_keybert dla child chunków (KeyBERT batch + regex).

  python backfill_keywords_keybert.py --limit 100
  python backfill_keywords_keybert.py --force
  python backfill_keywords_keybert.py --force --fast   # ~2× GPU + ~30× szybszy zapis DB

Po --fast na końcu uruchom: python rebuild_indexes.py
"""
from __future__ import annotations

import argparse
import atexit
import logging
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

from pipeline.db import prepare_keywords_backfill_fast, restore_keywords_backfill_triggers
from pipeline.keywords_keybert import (
    build_keybert_input,
    extract_keybert_phrases,
    merge_chunk_keywords,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("keybert_backfill")

POSTGRES_URL = os.getenv(
    "POSTGRES_URL",
    "postgresql://admin:admin@postgres:5432/papers_db_v2",
)
KEYBERT_MODEL = os.getenv("KEYBERT_MODEL", "BAAI/bge-small-en-v1.5")
BATCH = int(os.getenv("KEYBERT_BATCH", "512"))
MAX_KW = int(os.getenv("KEYBERT_MAX_KEYWORDS", "12"))
ENCODE_BATCH = int(os.getenv("KEYBERT_ENCODE_BATCH", "128"))

_FAST_TRIGGER_RESTORED = False


def _ensure_trigger_restored() -> None:
    global _FAST_TRIGGER_RESTORED
    if _FAST_TRIGGER_RESTORED:
        return
    try:
        restore_keywords_backfill_triggers()
        _FAST_TRIGGER_RESTORED = True
        logger.info("Trigger chunks_text_search_trg włączony ponownie")
    except Exception:
        logger.exception("Nie udało się włączyć triggera — uruchom ręcznie ENABLE TRIGGER")


def _load_keybert():
    from keybert import KeyBERT
    from keybert.backend import SentenceTransformerBackend
    from sentence_transformers import SentenceTransformer
    import torch

    device = os.getenv("KEYBERT_DEVICE", "").strip()
    if not device:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    encode_batch = int(os.getenv("KEYBERT_ENCODE_BATCH", "768"))
    logger.info("KeyBERT device: %s | encode_batch=%d", device, encode_batch)
    embedder = SentenceTransformer(KEYBERT_MODEL, device=device)
    if device == "cuda" and os.getenv("KEYBERT_FP16", "1") == "1":
        embedder.half()
        logger.info("KeyBERT precision: fp16")
    backend = SentenceTransformerBackend(embedder, batch_size=encode_batch)
    return KeyBERT(model=backend)


def _keybert_kwargs(*, fast: bool) -> dict:
    if fast:
        return {
            "max_keywords": int(os.getenv("KEYBERT_FAST_MAX_KEYWORDS", "8")),
            "ngram_range": (2, 2),
            "use_mmr": False,
            "nr_candidates": int(os.getenv("KEYBERT_FAST_NR_CANDIDATES", "10")),
        }
    return {
        "max_keywords": MAX_KW,
        "ngram_range": (2, 3),
        "use_mmr": True,
        "nr_candidates": 20,
    }


def fetch_batch(
    conn,
    *,
    limit: int,
    force: bool,
    after_id: str | None = None,
) -> list[tuple]:
    sql = """
        SELECT c.id::text, c.content, c.sacred_type, c.section_name,
               c.subsection_name, p.title
        FROM chunks c
        JOIN papers p ON p.id = c.paper_id
        WHERE c.chunk_role = 'child'
    """
    params: list = []
    if not force:
        sql += " AND (keywords_keybert IS NULL OR keywords_keybert = '{}')"
    if after_id:
        sql += " AND c.id > %s::uuid"
        params.append(after_id)
    sql += " ORDER BY c.id"
    if limit:
        sql += " LIMIT %s"
        params.append(limit)
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill keywords KeyBERT v2")
    parser.add_argument("--limit", type=int, default=0, help="0 = wszystkie")
    parser.add_argument("--force", action="store_true", help="Przetwórz także uzupełnione")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="DROP GIN/BM25, wyłącz trigger FTS, szybszy KeyBERT (rebuild_indexes na końcu)",
    )
    args = parser.parse_args()

    from psycopg import connect

    batch_size = int(os.getenv("KEYBERT_FAST_BATCH", "1024")) if args.fast else BATCH
    kb_kwargs = _keybert_kwargs(fast=args.fast)

    if args.fast:
        logger.info("Tryb FAST: DROP GIN/BM25, trigger OFF, batch=%d, kb=%s", batch_size, kb_kwargs)
        prepare_keywords_backfill_fast()
        atexit.register(_ensure_trigger_restored)

    logger.info(
        "Model: %s | batch=%d | baza=%s",
        KEYBERT_MODEL,
        batch_size,
        POSTGRES_URL.split("@")[-1],
    )
    kw_model = _load_keybert()
    total = 0
    after_id: str | None = None
    t0 = time.perf_counter()

    try:
        while True:
            batch_limit = batch_size
            if args.limit:
                remaining = args.limit - total
                if remaining <= 0:
                    break
                batch_limit = min(batch_size, remaining)

            with connect(POSTGRES_URL) as conn:
                rows = fetch_batch(
                    conn,
                    limit=batch_limit,
                    force=args.force,
                    after_id=after_id,
                )
                if not rows:
                    break

                inputs = [
                    build_keybert_input(
                        content,
                        paper_title=title or "",
                        section_name=section_name,
                        subsection_name=subsection_name,
                    )
                    for _, content, _, section_name, subsection_name, title in rows
                ]
                keybert_batch = extract_keybert_phrases(
                    kw_model,
                    inputs,
                    encode_batch_size=ENCODE_BATCH,
                    **kb_kwargs,
                )

                updates: list[tuple[list[str], list[str], str]] = []
                for row, kb in zip(rows, keybert_batch):
                    cid, content, sacred_type, section_name, subsection_name, title = row
                    regex_kw, kb_kw = merge_chunk_keywords(
                        content,
                        paper_title=title or "",
                        section_name=section_name,
                        subsection_name=subsection_name,
                        sacred_type=sacred_type,
                        keybert=kb,
                    )
                    if not kb_kw:
                        kb_kw = [""]
                    updates.append((regex_kw, kb_kw, cid))

                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        UPDATE chunks
                        SET keywords = %s, keywords_keybert = %s
                        WHERE id = %s::uuid
                        """,
                        updates,
                    )
                conn.commit()

            total += len(rows)
            after_id = rows[-1][0]
            rate = total / max(time.perf_counter() - t0, 1)
            logger.info(
                "Zaktualizowano: %d unikalnych (%.1f/s) | ostatni batch: %d",
                total,
                rate,
                len(rows),
            )

            if len(rows) < batch_limit:
                break
    finally:
        if args.fast:
            _ensure_trigger_restored()

    elapsed = time.perf_counter() - t0
    logger.info("Gotowe. Łącznie: %d w %.0fs (%.1f/s)", total, elapsed, total / max(elapsed, 1))
    if args.fast:
        logger.info("Następny krok: python rebuild_indexes.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
