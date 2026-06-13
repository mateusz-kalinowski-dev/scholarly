#!/usr/bin/env python3
"""Ocena KeyBERT na próbce child chunków — przed pełnym backfillem."""
from __future__ import annotations

import argparse
import os
import random
import textwrap

from dotenv import load_dotenv
from psycopg import connect

load_dotenv()

from v2.keywords import extract_keywords
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


def fetch_sample(conn, n: int, seed: int) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id::text, c.content, c.sacred_type, c.section_name,
                   c.subsection_name, p.title, p.arxiv_id,
                   c.keywords, c.keywords_keybert
            FROM chunks c
            JOIN papers p ON p.id = c.paper_id
            WHERE c.chunk_role = 'child'
              AND length(c.content) BETWEEN 120 AND 2500
              AND c.sacred_type IS NULL
            ORDER BY md5(c.id::text || %s)
            LIMIT %s
            """,
            (str(seed), n),
        )
        return cur.fetchall()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=12)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    from keybert import KeyBERT

    print(f"Model: {KEYBERT_MODEL}")
    kw_model = KeyBERT(model=KEYBERT_MODEL)

    with connect(POSTGRES_V2_URL) as conn:
        rows = fetch_sample(conn, args.sample, args.seed)

    print(f"Próbka: {len(rows)} chunków (proza, 120–2500 znaków)\n")
    kb_nonempty = 0
    regex_only = 0

    for i, row in enumerate(rows, 1):
        (
            cid,
            content,
            sacred_type,
            section_name,
            subsection_name,
            title,
            arxiv_id,
            old_kw,
            old_kb,
        ) = row

        inp = build_keybert_input(
            content,
            paper_title=title or "",
            section_name=section_name,
            subsection_name=subsection_name,
        )
        kb = extract_keybert_phrases(kw_model, [inp], max_keywords=12)[0]
        regex_kw, kb_kw = merge_chunk_keywords(
            content,
            paper_title=title or "",
            section_name=section_name,
            subsection_name=subsection_name,
            sacred_type=sacred_type,
            keybert=kb,
        )
        if kb_kw:
            kb_nonempty += 1
        else:
            regex_only += 1

        preview = textwrap.shorten(content.replace("\n", " "), width=140)
        print(f"--- [{i}] {arxiv_id} | {section_name or 'N/A'} ---")
        print(f"Treść: {preview}")
        print(f"Regex ({len(regex_kw)}): {', '.join(regex_kw[:10])}")
        print(f"KeyBERT ({len(kb_kw)}): {', '.join(kb_kw[:10]) or '(brak)'}")
        if old_kb:
            print(f"W bazie już KB: {', '.join(old_kb[:6])}")
        print()

    print("=== Podsumowanie próbki ===")
    print(f"  chunków z KeyBERT phrases: {kb_nonempty}/{len(rows)}")
    print(f"  tylko regex (krótkie/święte): {regex_only}/{len(rows)}")
    avg_kb = kb_nonempty / max(len(rows), 1)
    print(f"  hit rate KeyBERT: {avg_kb:.0%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
