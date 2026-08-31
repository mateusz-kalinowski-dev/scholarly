#!/usr/bin/env python3
"""
Baseline 0 (praca.md): surowy tekst -> RecursiveCharacterTextSplitter 1000 znaków
-> embedding chunka (bge-m3) -> baseline0_chunks w postgres.

Szybkość: równoległe workery (MinIO+split + embed) + duże batch'e Ollama.

  py build_baseline0.py --ensure-schema
  py build_baseline0.py --limit 5
  py build_baseline0.py --truncate
  py build_baseline0.py --build-index

Env: B0_PAPER_WORKERS=8 B0_EMBED_WORKERS=4 B0_EMBED_BATCH_SIZE=64
     B0_EMBED_ACCUMULATE=256 EMBED_BATCH_PAUSE=0
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()

from baseline0.config import (
    B0_CHUNK_OVERLAP,
    B0_CHUNK_SIZE,
    B0_DB_INSERT_BATCH,
    B0_EMBED_ACCUMULATE,
    B0_EMBED_BATCH_SIZE,
    B0_EMBED_MAX_INFLIGHT,
    B0_EMBED_SERIAL,
    B0_EMBED_WORKERS,
    B0_PAPER_WORKERS,
)
from baseline0.db import (
    build_hnsw_index,
    clear_baseline0,
    count_chunks,
    delete_paper_chunks,
    ensure_schema,
    insert_chunks_batch,
    list_papers,
    save_meta,
)
from baseline0.splitter import recursive_character_split
import config as app_config
from config import EMBED_DIM, EMBED_MODEL
from pipeline.embeddings import embed_texts
from pipeline.minio_fetch import load_text_from_storage_path
from pipeline.sanitize import sanitize_db_text

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("build_baseline0")

_OLLAMA_EMBED_LOCK = threading.Lock()


@dataclass
class PendingRow:
    paper_id: str
    chunk_index: int
    content: str


@dataclass
class BuildStats:
    papers: int = 0
    chunks: int = 0
    embed_batches: int = 0
    errors: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add_paper(self) -> None:
        with self._lock:
            self.papers += 1

    def add_error(self, n: int = 1) -> None:
        with self._lock:
            self.errors += n

    def add_embed_result(self, chunks: int, embed_batches: int, errors: int) -> None:
        with self._lock:
            self.chunks += chunks
            self.embed_batches += embed_batches
            self.errors += errors


@dataclass
class ChunkPaperResult:
    arxiv_id: str
    rows: list[PendingRow]
    error: str | None = None


def chunk_paper(paper: dict) -> ChunkPaperResult:
    arxiv_id = paper["arxiv_id"]
    paper_id = paper["id"]
    try:
        raw = load_text_from_storage_path(paper["storage_path"])
    except Exception as e:
        return ChunkPaperResult(arxiv_id, [], str(e))

    if not raw.strip():
        return ChunkPaperResult(arxiv_id, [], "pusty tekst")

    delete_paper_chunks(paper_id)
    pieces = recursive_character_split(
        raw,
        chunk_size=B0_CHUNK_SIZE,
        chunk_overlap=B0_CHUNK_OVERLAP,
    )
    if not pieces:
        return ChunkPaperResult(arxiv_id, [], "brak chunków")

    rows: list[PendingRow] = []
    for idx, piece in enumerate(pieces):
        content = sanitize_db_text(piece)
        if content.strip():
            rows.append(PendingRow(paper_id, idx, content))
    return ChunkPaperResult(arxiv_id, rows)


def embed_and_insert_batch(batch: list[PendingRow]) -> tuple[int, int, int]:
    """Zwraca (chunks_ok, embed_sub_batches, errors)."""
    if not batch:
        return 0, 0, 0

    texts = [r.content for r in batch]
    t0 = time.perf_counter()
    if B0_EMBED_SERIAL:
        with _OLLAMA_EMBED_LOCK:
            vectors = embed_texts(texts)
    else:
        vectors = embed_texts(texts)
    sub_batches = max(1, (len(texts) + B0_EMBED_BATCH_SIZE - 1) // B0_EMBED_BATCH_SIZE)
    elapsed = time.perf_counter() - t0

    db_rows: list[tuple[str, int, str, list[float] | None]] = []
    errors = 0
    for row, vec in zip(batch, vectors, strict=True):
        if vec is None:
            errors += 1
        db_rows.append((row.paper_id, row.chunk_index, row.content, vec))

    for offset in range(0, len(db_rows), B0_DB_INSERT_BATCH):
        insert_chunks_batch(db_rows[offset : offset + B0_DB_INSERT_BATCH])

    logger.info("Embed+insert %d chunków w %.1fs (%d błędów)", len(batch), elapsed, errors)
    return len(batch), sub_batches, errors


class EmbedScheduler:
    def __init__(self, stats: BuildStats) -> None:
        self.stats = stats
        self._executor = ThreadPoolExecutor(max_workers=B0_EMBED_WORKERS)
        self._inflight: list[Future] = []
        self._lock = threading.Lock()

    def submit(self, batch: list[PendingRow]) -> None:
        if not batch:
            return
        self._drain_done()
        while len(self._inflight) >= B0_EMBED_MAX_INFLIGHT:
            self._wait_one()
        fut = self._executor.submit(embed_and_insert_batch, batch)
        with self._lock:
            self._inflight.append(fut)

    def flush(self) -> None:
        with self._lock:
            pending = list(self._inflight)
        for fut in as_completed(pending):
            self._collect(fut)
        with self._lock:
            self._inflight.clear()

    def _drain_done(self) -> None:
        with self._lock:
            done = [f for f in self._inflight if f.done()]
            self._inflight = [f for f in self._inflight if not f.done()]
        for fut in done:
            self._collect(fut)

    def _wait_one(self) -> None:
        with self._lock:
            if not self._inflight:
                return
            fut = self._inflight[0]
        fut.result()
        self._collect(fut)
        with self._lock:
            if fut in self._inflight:
                self._inflight.remove(fut)

    def _collect(self, fut: Future) -> None:
        try:
            chunks, sub_batches, errors = fut.result()
            self.stats.add_embed_result(chunks, sub_batches, errors)
        except Exception as e:
            logger.exception("Embed job failed: %s", e)
            self.stats.add_error()

    def shutdown(self) -> None:
        self.flush()
        self._executor.shutdown(wait=True)


def run_build(*, limit: int | None, truncate: bool, resume: bool) -> BuildStats:
    if truncate:
        logger.info("TRUNCATE baseline0_chunks")
        clear_baseline0()

    papers = list_papers(limit=limit, only_unprocessed=(resume and not truncate))
    logger.info(
        "Papers: %d | resume=%s | chunk=%d overlap=%d | accumulate=%d embed_batch=%d | "
        "paper_workers=%d embed_workers=%d serial_ollama=%s max_inflight=%d | model=%s",
        len(papers),
        resume and not truncate,
        B0_CHUNK_SIZE,
        B0_CHUNK_OVERLAP,
        B0_EMBED_ACCUMULATE,
        B0_EMBED_BATCH_SIZE,
        B0_PAPER_WORKERS,
        B0_EMBED_WORKERS,
        B0_EMBED_SERIAL,
        B0_EMBED_MAX_INFLIGHT,
        EMBED_MODEL,
    )

    stats = BuildStats()
    scheduler = EmbedScheduler(stats)
    accumulate: list[PendingRow] = []
    acc_lock = threading.Lock()
    t0 = time.perf_counter()
    done_papers = 0

    def flush_accumulate() -> None:
        nonlocal accumulate
        with acc_lock:
            if not accumulate:
                return
            batch = accumulate
            accumulate = []
        scheduler.submit(batch)

    with ThreadPoolExecutor(max_workers=B0_PAPER_WORKERS) as paper_pool:
        futures = {paper_pool.submit(chunk_paper, p): p for p in papers}
        for fut in as_completed(futures):
            result = fut.result()
            done_papers += 1
            if result.error:
                stats.add_error()
                logger.warning("[%s] %s", result.arxiv_id, result.error)
            else:
                stats.add_paper()
                with acc_lock:
                    accumulate.extend(result.rows)
                    while len(accumulate) >= B0_EMBED_ACCUMULATE:
                        batch = accumulate[:B0_EMBED_ACCUMULATE]
                        accumulate = accumulate[B0_EMBED_ACCUMULATE:]
                        scheduler.submit(batch)

            if done_papers % 100 == 0:
                logger.info(
                    "Postęp chunk: %d/%d prac, %d chunków w DB",
                    done_papers,
                    len(papers),
                    stats.chunks,
                )

    with acc_lock:
        tail = accumulate
        accumulate = []
    if tail:
        scheduler.submit(tail)

    scheduler.shutdown()

    save_meta(
        chunk_size=B0_CHUNK_SIZE,
        chunk_overlap=B0_CHUNK_OVERLAP,
        embed_model=EMBED_MODEL,
        embed_dim=EMBED_DIM,
        papers_total=stats.papers,
        chunks_total=count_chunks(),
    )
    logger.info(
        "GOTOWE: %d prac, %d chunków, ~%d sub-batchy embed, %d błędów, %.1fs",
        stats.papers,
        stats.chunks,
        stats.embed_batches,
        stats.errors,
        time.perf_counter() - t0,
    )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Baseline 0 — naiwny chunk + embed")
    parser.add_argument("--ensure-schema", action="store_true", help="Migracja SQL tabel")
    parser.add_argument("--build-index", action="store_true", help="HNSW na embedding")
    parser.add_argument("--limit", type=int, default=None, help="Max liczba prac (test)")
    parser.add_argument("--truncate", action="store_true", help="Wyczyść przed buildem")
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Pomijaj papiery już obecne w baseline0_chunks (domyślnie: włączone)",
    )
    parser.add_argument("--paper-workers", type=int, default=None)
    parser.add_argument("--embed-workers", type=int, default=None)
    args = parser.parse_args()

    global B0_PAPER_WORKERS, B0_EMBED_WORKERS
    if args.paper_workers is not None:
        B0_PAPER_WORKERS = args.paper_workers
    if args.embed_workers is not None:
        B0_EMBED_WORKERS = args.embed_workers

    if args.ensure_schema:
        ensure_schema()
        logger.info("Schema baseline0 OK")
        if not args.build_index and args.limit is None:
            return 0

    if args.build_index:
        ensure_schema()
        build_hnsw_index()
        logger.info("HNSW baseline0_chunks OK (%d wierszy)", count_chunks())
        return 0

    ensure_schema()
    os.environ.setdefault("EMBED_BATCH_PAUSE", "0")
    app_config.EMBED_BATCH_SIZE = B0_EMBED_BATCH_SIZE
    run_build(limit=args.limit, truncate=args.truncate, resume=args.resume)
    return 0


if __name__ == "__main__":
    sys.exit(main())
