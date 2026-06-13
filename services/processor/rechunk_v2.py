#!/usr/bin/env python3
"""
Rechunk + embed pojedynczej pracy v2 (dev / reprocess) oraz budowanie indeksów.

  python rechunk_v2.py --arxiv-id 2605.08376
  python rechunk_v2.py --build-indexes
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

from dotenv import load_dotenv

load_dotenv()

from v2.chunking import build_parent_child_chunks
from v2.config import EMBED_MODEL
from v2.db import (
    build_search_indexes,
    get_paper_for_rechunk,
    list_child_contents,
    save_parent_child_chunks,
    update_child_embeddings,
    update_paper_embeddings,
)
from v2.embeddings import embed_texts
from v2.minio_fetch import load_text_from_storage_path
from v2.parsing import parse_sections

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("rechunk_v2")


def process_paper(paper: dict) -> None:
    paper_id = paper["id"]
    arxiv_id = paper["arxiv_id"]
    t0 = time.perf_counter()
    logger.info("[%s] Start rechunk v2", arxiv_id)

    raw = load_text_from_storage_path(paper["storage_path"])
    if not raw.strip():
        raise ValueError("Pusty tekst w MinIO")

    sections = parse_sections(raw)
    parents = build_parent_child_chunks(sections, paper_title=paper["title"])
    if not parents:
        raise ValueError("Brak parent chunków")

    p_count, c_count = save_parent_child_chunks(paper_id, parents)
    logger.info("[%s] Chunki: %d parent, %d child", arxiv_id, p_count, c_count)

    children = list_child_contents(paper_id)
    if not children:
        raise ValueError("Brak child chunków")

    vectors = embed_texts([content for _, content in children])
    pairs = [
        (cid, emb)
        for (cid, _), emb in zip(children, vectors)
        if emb is not None
    ]
    if len(pairs) != len(children):
        raise ValueError(f"Niepełne embeddingi child ({len(pairs)}/{len(children)})")
    update_child_embeddings(pairs)
    logger.info("[%s] Embeddingi child: %d", arxiv_id, len(pairs))

    title_vec = embed_texts([paper["title"]])[0]
    summary = paper.get("summary") or ""
    summary_vec = embed_texts([summary])[0] if summary.strip() else None
    if not title_vec:
        raise ValueError("Brak embeddingu tytułu")

    update_paper_embeddings(paper_id, title_vec, summary_vec, EMBED_MODEL)
    logger.info("[%s] DONE w %.1fs", arxiv_id, time.perf_counter() - t0)


def main() -> int:
    parser = argparse.ArgumentParser(description="Rechunk v2 → postgres_v2")
    parser.add_argument("--arxiv-id", type=str, default=None)
    parser.add_argument("--build-indexes", action="store_true")
    args = parser.parse_args()

    if args.build_indexes:
        logger.info("Budowanie indeksów HNSW + GIN + BM25...")
        build_search_indexes()
        logger.info("Indeksy gotowe.")
        return 0

    if not args.arxiv_id:
        parser.error("Podaj --arxiv-id lub użyj --build-indexes")

    paper = get_paper_for_rechunk(args.arxiv_id)
    if not paper:
        logger.error("Nie znaleziono pracy: %s", args.arxiv_id)
        return 1

    try:
        process_paper(paper)
    except Exception as e:
        logger.error("[%s] FAILED: %s", args.arxiv_id, e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
