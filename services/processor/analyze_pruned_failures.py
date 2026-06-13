#!/usr/bin/env python3
"""
Analiza 1466 prac usuniętych z v2 (brak paper_embeddings).
Odtwarza przyczynę z MinIO + symuluje embedding problematycznych chunków.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict

from dotenv import load_dotenv

load_dotenv()

from psycopg import connect

from v2.chunking import build_parent_child_chunks
from v2.config import EMBED_MODEL, POSTGRES_V2_URL
from v2.embeddings import embed_texts
from v2.minio_fetch import load_text_from_storage_path
from v2.parsing import parse_sections, prepare_raw_document, clean_text

V1_URL = "postgresql://admin:admin@postgres:5432/papers_db"


def get_pruned_papers(limit: int | None = None) -> list[dict]:
    with connect(V1_URL) as v1, connect(POSTGRES_V2_URL) as v2:
        with v2.cursor() as cur:
            cur.execute("SELECT arxiv_id FROM papers")
            v2_ids = {r[0] for r in cur.fetchall()}
        with v1.cursor() as cur:
            cur.execute(
                """
                SELECT arxiv_id, title, storage_path, embedding_status,
                       chunking_status, parsing_status
                FROM papers
                WHERE storage_path IS NOT NULL
                ORDER BY arxiv_id
                """
            )
            cols = [d.name for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall() if r[0] not in v2_ids]
    if limit:
        return rows[:limit]
    return rows


def classify_paper(paper: dict, *, test_embed: bool = True) -> tuple[str, str, list[str]]:
    """Zwraca (kategoria, szczegóły, przykładowe child bez embeda)."""
    arxiv_id = paper["arxiv_id"]
    try:
        raw = load_text_from_storage_path(paper["storage_path"])
    except Exception as e:
        return "minio_error", str(e), []

    if not raw.strip():
        return "empty_minio", "pusty plik", []

    doc = prepare_raw_document(raw)
    if len(doc.strip()) < 50:
        return "empty_after_prepare", f"doc_len={len(doc.strip())}", []

    sections = parse_sections(raw)
    if not sections:
        return "no_sections", "parse_sections=[]", []

    try:
        parents = build_parent_child_chunks(sections, paper_title=paper["title"])
    except Exception as e:
        return "chunking_crash", f"{type(e).__name__}: {e}", []

    if not parents:
        has_input = bool(re.search(r"\\input\{", raw, re.I))
        only_figures = bool(re.search(r"\\begin\{figure", raw, re.I)) and len(
            clean_text(doc)
        ) < 30
        if has_input:
            return "stub_input_only", r"\input{sections/...} bez treści", []
        if only_figures:
            return "figures_only", "tylko figury, brak prozy", []
        return "no_parent_chunks", "clean_text wyczyścił wszystko", []

    child_texts: list[str] = []
    for p in parents:
        for c in p.children:
            if c.content.strip():
                child_texts.append(c.content)

    if not child_texts:
        return "no_child_chunks", "0 child po chunkingu", []

    if test_embed:
        sample = child_texts[:8]
        vectors = embed_texts(sample)
        failed_idx = [i for i, v in enumerate(vectors) if v is None]
        if failed_idx:
            examples = [sample[i][:200] for i in failed_idx[:3]]
            return (
                "ollama_embed_fail",
                f"{len(failed_idx)}/{len(sample)} chunków bez wektora w próbce",
                examples,
            )

    return "chunked_not_finished", (
        f"chunki wygenerowane ({len(child_texts)} child), embed nie dokończony w rechunk"
    ), []


def main() -> int:
    parser = argparse.ArgumentParser(description="Analiza prac usuniętych z v2")
    parser.add_argument("--limit", type=int, default=80, help="Ile prac przeanalizować")
    parser.add_argument("--full", action="store_true", help="Wszystkie ~1466 (wolne)")
    parser.add_argument(
        "--skip-embed",
        action="store_true",
        help="Bez testu Ollama (szybka klasyfikacja)",
    )
    args = parser.parse_args()

    limit = None if args.full else args.limit
    papers = get_pruned_papers(limit=limit)
    test_embed = not args.skip_embed
    print(f"Prac do analizy: {len(papers)} (usunięte z v2, dane z v1+MinIO)\n")

    categories: Counter[str] = Counter()
    details: dict[str, list[str]] = defaultdict(list)
    embed_examples: list[tuple[str, str]] = []

    for i, paper in enumerate(papers, 1):
        cat, detail, examples = classify_paper(paper, test_embed=test_embed)
        categories[cat] += 1
        if len(details[cat]) < 3:
            details[cat].append(f"{paper['arxiv_id']}: {detail}")
        for ex in examples:
            embed_examples.append((paper["arxiv_id"], ex))
        if i % 20 == 0:
            print(f"  ... {i}/{len(papers)}", file=sys.stderr)

    print("=== Kategorie porażek ===")
    for cat, n in categories.most_common():
        pct = 100 * n / len(papers)
        print(f"  {cat:22s} {n:5d} ({pct:5.1f}%)")
        for d in details[cat]:
            print(f"    · {d}")

    if embed_examples:
        print("\n=== Przykładowe chunki z failującym embedem (Ollama/bge-m3) ===")
        for aid, text in embed_examples[:8]:
            print(f"\n[{aid}]")
            print(text.replace("\n", " "))

    print(f"\nModel embed: {EMBED_MODEL}")
    print("Uwaga: pełna baza v2 ma już 0 chunków bez embeddingu — to analiza retrospektywna.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
