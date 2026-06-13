#!/usr/bin/env python3
"""
Benchmark KeyBERT backfill — BEZ zapisu do bazy (UPDATE z ROLLBACK tylko do pomiaru DB).

  python bench_keybert_throughput.py
  python bench_keybert_throughput.py --chunks 2048 --warmup 256
  python bench_keybert_throughput.py --skip-db

Mierzy:
  - strategie ekstrakcji KeyBERT (GPU)
  - koszt SELECT + UPDATE (trigger + indeksy GIN/BM25)
  - pełny pipeline dry-run (GPU + DB rollback)
"""
from __future__ import annotations

import argparse
import os
import statistics
import time
from dataclasses import dataclass
from typing import Any, Callable

from dotenv import load_dotenv

load_dotenv()

from v2.keywords_keybert import (
    build_keybert_input,
    extract_keybert_phrases,
    merge_chunk_keywords,
)

POSTGRES_V2_URL = os.getenv(
    "POSTGRES_V2_URL",
    "postgresql://admin:admin@postgres_v2:5432/papers_db_v2",
)
KEYBERT_MODEL = os.getenv("KEYBERT_MODEL", "BAAI/bge-small-en-v1.5")


@dataclass(frozen=True)
class GpuStrategy:
    name: str
    ngram: tuple[int, int]
    use_mmr: bool
    diversity: float
    top_n: int
    nr_candidates: int
    input_mode: str  # full | content_only
    skip_math: bool


@dataclass(frozen=True)
class BenchResult:
    name: str
    chunks: int
    seconds: float
    rate: float
    notes: str = ""

    def __str__(self) -> str:
        extra = f"  ({self.notes})" if self.notes else ""
        return f"{self.name:40s} {self.rate:7.1f}/s  [{self.chunks} ch, {self.seconds:.1f}s]{extra}"


def load_keybert():
    from keybert import KeyBERT
    from sentence_transformers import SentenceTransformer
    import torch

    device = os.getenv("KEYBERT_DEVICE", "").strip()
    if not device:
        device = "cuda" if torch.cuda.is_available() else "cpu"
    embedder = SentenceTransformer(KEYBERT_MODEL, device=device)
    if device == "cuda" and os.getenv("KEYBERT_FP16", "1") == "1":
        embedder.half()
    return KeyBERT(model=embedder), device


def fetch_chunks(conn, *, limit: int, skip_math: bool) -> list[tuple]:
    sql = """
        SELECT c.id::text, c.content, c.sacred_type, c.section_name,
               c.subsection_name, p.title
        FROM chunks c
        JOIN papers p ON p.id = c.paper_id
        WHERE c.chunk_role = 'child'
    """
    if skip_math:
        sql += " AND (c.sacred_type IS NULL OR c.sacred_type = 'table')"
    sql += " ORDER BY c.id LIMIT %s"
    with conn.cursor() as cur:
        cur.execute(sql, (limit,))
        return cur.fetchall()


def build_inputs(
    rows: list[tuple],
    *,
    input_mode: str,
) -> list[str]:
    out: list[str] = []
    for _, content, _, section_name, subsection_name, title in rows:
        if input_mode == "content_only":
            out.append(content[:6000])
        else:
            out.append(
                build_keybert_input(
                    content,
                    paper_title=title or "",
                    section_name=section_name,
                    subsection_name=subsection_name,
                )
            )
    return out


def extract_with_strategy(
    kw_model,
    texts: list[str],
    *,
    strategy: GpuStrategy,
    max_keywords: int,
) -> list[list[str]]:
    if strategy.input_mode != "full":
        # bench wariantów inputu — używamy już przygotowanych texts
        pass

    cleaned = texts
    eligible = [i for i, t in enumerate(cleaned) if len(t.strip()) >= 40]
    out: list[list[str]] = [[] for _ in texts]
    if not eligible:
        return out

    batch_results = kw_model.extract_keywords(
        [cleaned[i] for i in eligible],
        keyphrase_ngram_range=strategy.ngram,
        stop_words="english",
        top_n=strategy.top_n or max_keywords,
        use_mmr=strategy.use_mmr,
        diversity=strategy.diversity,
        nr_candidates=strategy.nr_candidates,
    )
    if not isinstance(batch_results[0], list):
        batch_results = [batch_results]

    for idx, pairs in zip(eligible, batch_results):
        phrases: list[str] = []
        for item in pairs:
            phrase = str(item[0]) if isinstance(item, (list, tuple)) and item else str(item)
            if phrase.strip() and len(phrase.strip()) > 2:
                phrases.append(phrase.strip())
        out[idx] = phrases
    return out


def bench_gpu_strategy(
    kw_model,
    rows: list[tuple],
    strategy: GpuStrategy,
    *,
    max_keywords: int = 12,
) -> BenchResult:
    inputs = build_inputs(rows, input_mode=strategy.input_mode)
    work_rows = rows
    if strategy.skip_math:
        work_rows = [r for r in rows if r[2] not in ("equation", "display_math", "inline_math")]
        inputs = build_inputs(work_rows, input_mode=strategy.input_mode)

    t0 = time.perf_counter()
    kb_batch = extract_with_strategy(
        kw_model, inputs, strategy=strategy, max_keywords=max_keywords
    )
    for row, kb in zip(work_rows, kb_batch):
        _, content, sacred_type, section_name, subsection_name, title = row
        merge_chunk_keywords(
            content,
            paper_title=title or "",
            section_name=section_name,
            subsection_name=subsection_name,
            sacred_type=sacred_type,
            keybert=kb,
        )
    elapsed = time.perf_counter() - t0
    n = len(work_rows)
    return BenchResult(
        strategy.name,
        n,
        elapsed,
        n / max(elapsed, 1e-6),
        notes=f"kb_hit={sum(1 for k in kb_batch if k)}/{n}",
    )


def bench_current_extract(
    kw_model,
    rows: list[tuple],
    *,
    encode_batch_size: int,
) -> BenchResult:
    inputs = [
        build_keybert_input(
            content,
            paper_title=title or "",
            section_name=section_name,
            subsection_name=subsection_name,
        )
        for _, content, _, section_name, subsection_name, title in rows
    ]
    t0 = time.perf_counter()
    kb_batch = extract_keybert_phrases(
        kw_model, inputs, max_keywords=12, encode_batch_size=encode_batch_size
    )
    for row, kb in zip(rows, kb_batch):
        _, content, sacred_type, section_name, subsection_name, title = row
        merge_chunk_keywords(
            content,
            paper_title=title or "",
            section_name=section_name,
            subsection_name=subsection_name,
            sacred_type=sacred_type,
            keybert=kb,
        )
    elapsed = time.perf_counter() - t0
    n = len(rows)
    return BenchResult(
        "current pipeline (extract_keybert_phrases)",
        n,
        elapsed,
        n / max(elapsed, 1e-6),
        notes=f"kb_hit={sum(1 for k in kb_batch if k)}/{n}",
    )


def bench_db_phase(
    conn,
    rows: list[tuple],
    *,
    disable_trigger: bool,
    label: str,
) -> BenchResult:
    updates: list[tuple[list[str], list[str], str]] = []
    for row in rows:
        cid, content, sacred_type, section_name, subsection_name, title = row
        regex_kw, kb_kw = merge_chunk_keywords(
            content,
            paper_title=title or "",
            section_name=section_name,
            subsection_name=subsection_name,
            sacred_type=sacred_type,
            keybert=["benchmark phrase"],
        )
        if not kb_kw:
            kb_kw = [""]
        updates.append((regex_kw, kb_kw, cid))

    with conn.cursor() as cur:
        if disable_trigger:
            cur.execute("ALTER TABLE chunks DISABLE TRIGGER chunks_text_search_trg")
        t0 = time.perf_counter()
        cur.executemany(
            """
            UPDATE chunks
            SET keywords = %s, keywords_keybert = %s
            WHERE id = %s::uuid
            """,
            updates,
        )
        elapsed = time.perf_counter() - t0
        conn.rollback()
        if disable_trigger:
            cur.execute("ALTER TABLE chunks ENABLE TRIGGER chunks_text_search_trg")
        conn.rollback()

    n = len(rows)
    return BenchResult(label, n, elapsed, n / max(elapsed, 1e-6))


def bench_select(conn, *, limit: int, skip_math: bool) -> BenchResult:
    t0 = time.perf_counter()
    rows = fetch_chunks(conn, limit=limit, skip_math=skip_math)
    elapsed = time.perf_counter() - t0
    n = len(rows)
    return BenchResult("SELECT batch (JOIN papers)", n, elapsed, n / max(elapsed, 1e-6))


def bench_full_dry_run(
    kw_model,
    conn,
    rows: list[tuple],
    *,
    gpu_strategy: GpuStrategy,
    disable_trigger: bool,
) -> BenchResult:
    inputs = build_inputs(rows, input_mode=gpu_strategy.input_mode)
    label = f"full dry-run | GPU={gpu_strategy.name} | trigger={'OFF' if disable_trigger else 'ON'}"

    t0 = time.perf_counter()
    kb_batch = extract_with_strategy(kw_model, inputs, strategy=gpu_strategy, max_keywords=12)
    updates: list[tuple[list[str], list[str], str]] = []
    for row, kb in zip(rows, kb_batch):
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
        if disable_trigger:
            cur.execute("ALTER TABLE chunks DISABLE TRIGGER chunks_text_search_trg")
        cur.executemany(
            """
            UPDATE chunks
            SET keywords = %s, keywords_keybert = %s
            WHERE id = %s::uuid
            """,
            updates,
        )
        conn.rollback()
        if disable_trigger:
            cur.execute("ALTER TABLE chunks ENABLE TRIGGER chunks_text_search_trg")
        conn.rollback()

    elapsed = time.perf_counter() - t0
    n = len(rows)
    return BenchResult(label, n, elapsed, n / max(elapsed, 1e-6))


def print_section(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark KeyBERT backfill (no persist)")
    parser.add_argument("--chunks", type=int, default=1024, help="Rozmiar jednej próbki")
    parser.add_argument("--warmup", type=int, default=128, help="Chunki rozgrzewki GPU")
    parser.add_argument("--skip-db", action="store_true", help="Tylko GPU, bez testów DB")
    parser.add_argument("--skip-gpu", action="store_true", help="Tylko DB")
    args = parser.parse_args()

    from psycopg import connect

    print(f"Model: {KEYBERT_MODEL}")
    print(f"Próbka: {args.chunks} chunków | warmup: {args.warmup}")
    print("UWAGA: UPDATE w testach DB kończy się ROLLBACK — dane NIE są zapisywane.")

    kw_model = None
    device = "cpu"
    if not args.skip_gpu:
        kw_model, device = load_keybert()
        print(f"Device: {device}")

    results: list[BenchResult] = []

    with connect(POSTGRES_V2_URL) as conn:
        rows = fetch_chunks(conn, limit=args.chunks, skip_math=False)
        if len(rows) < args.chunks:
            print(f"Pobrano {len(rows)} chunków (mniej niż --chunks)")

        if not args.skip_db:
            print_section("1. Koszt I/O bazy (bez zapisu)")
            results.append(bench_select(conn, limit=args.chunks, skip_math=False))
            results.append(bench_select(conn, limit=args.chunks, skip_math=True))

        if not args.skip_gpu and kw_model is not None:
            warmup_rows = rows[: min(args.warmup, len(rows))]
            if warmup_rows:
                print_section("0. Rozgrzewka GPU")
                extract_keybert_phrases(
                    kw_model,
                    build_inputs(warmup_rows, input_mode="full"),
                    max_keywords=12,
                )
                print(f"Warmup OK ({len(warmup_rows)} chunków)")

            print_section("2. Strategie KeyBERT + merge (tylko GPU, bez DB)")
            results.append(bench_current_extract(kw_model, rows, encode_batch_size=128))

            gpu_strategies = [
                GpuStrategy("mmr ngram(2,3) top12", (2, 3), True, 0.4, 12, 20, "full", False),
                GpuStrategy("no_mmr ngram(2,3) top12", (2, 3), False, 0.4, 12, 20, "full", False),
                GpuStrategy("no_mmr ngram(2,3) top8", (2, 3), False, 0.4, 8, 12, "full", False),
                GpuStrategy("no_mmr ngram(2,2) top8", (2, 2), False, 0.4, 8, 10, "full", False),
                GpuStrategy("no_mmr content_only top8", (2, 3), False, 0.4, 8, 12, "content_only", False),
                GpuStrategy("no_mmr skip_math rows", (2, 3), False, 0.4, 8, 12, "full", True),
            ]
            for strategy in gpu_strategies:
                results.append(bench_gpu_strategy(kw_model, rows, strategy))

        if not args.skip_db:
            print_section("3. Koszt UPDATE (ROLLBACK — bez trwałego zapisu)")
            results.append(
                bench_db_phase(
                    conn,
                    rows,
                    disable_trigger=False,
                    label="UPDATE trigger ON + GIN/BM25",
                )
            )
            results.append(
                bench_db_phase(
                    conn,
                    rows,
                    disable_trigger=True,
                    label="UPDATE trigger OFF (fast path)",
                )
            )

        if not args.skip_gpu and not args.skip_db and kw_model is not None:
            print_section("4. Pełny pipeline dry-run (GPU + DB rollback)")
            best_gpu = GpuStrategy(
                "no_mmr ngram(2,3) top8", (2, 3), False, 0.4, 8, 12, "full", False
            )
            results.append(
                bench_full_dry_run(
                    kw_model,
                    conn,
                    rows,
                    gpu_strategy=best_gpu,
                    disable_trigger=False,
                )
            )
            results.append(
                bench_full_dry_run(
                    kw_model,
                    conn,
                    rows,
                    gpu_strategy=best_gpu,
                    disable_trigger=True,
                )
            )

    print_section("WYNIKI")
    for r in results:
        print(r)

    gpu_rates = [r.rate for r in results if "UPDATE" not in r.name and "SELECT" not in r.name and "dry-run" not in r.name]
    db_on = next((r for r in results if r.name == "UPDATE trigger ON + GIN/BM25"), None)
    db_off = next((r for r in results if r.name == "UPDATE trigger OFF (fast path)"), None)
    current = next((r for r in results if r.name.startswith("current pipeline")), None)
    fast_gpu = max(
        (r for r in results if "no_mmr" in r.name and "dry-run" not in r.name),
        key=lambda r: r.rate,
        default=None,
    )

    print_section("REKOMENDACJA")
    if current:
        print(f"Obecny pipeline:     ~{current.rate:.0f}/s (GPU+merge, bez DB)")
    if fast_gpu:
        print(f"Najszybszy GPU:      ~{fast_gpu.rate:.0f}/s ({fast_gpu.name})")
    if db_on and db_off:
        print(f"DB trigger ON:       ~{db_on.rate:.0f}/s")
        print(f"DB trigger OFF:      ~{db_off.rate:.0f}/s  (×{db_off.rate/max(db_on.rate,1):.1f})")
    if fast_gpu and db_off:
        est = 1.0 / (1.0 / fast_gpu.rate + 1.0 / db_off.rate)
        print(f"Szacunek fast path:  ~{est:.0f}/s end-to-end")
        print(f"397k chunków @ {est:.0f}/s ≈ {397_549 / max(est, 1) / 3600:.1f} h")
    print()
    print("Fast backfill (do wdrożenia w backfill_keywords_keybert.py):")
    print("  1. DROP GIN + BM25 przed startem (rebuild_indexes_v2.py na końcu)")
    print("  2. DISABLE TRIGGER chunks_text_search_trg podczas UPDATE")
    print("  3. KeyBERT: use_mmr=False, top_n=8, nr_candidates=12, ngram (2,3)")
    print("  4. Większy batch (1024–2048), jedna sesja DB na batch")
    print("  5. Na końcu: refresh_child_text_search + rebuild_indexes_v2.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
