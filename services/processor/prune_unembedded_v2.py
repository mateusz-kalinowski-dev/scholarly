#!/usr/bin/env python3
"""Usuwa z postgres_v2 prace bez wiersza w paper_embeddings (CASCADE → chunki, golden_qa)."""
from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

load_dotenv()

from psycopg import connect

from v2.config import POSTGRES_V2_URL


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune papers bez paper_embeddings")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Tylko policz, bez DELETE",
    )
    args = parser.parse_args()

    with connect(POSTGRES_V2_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM papers")
            papers_before = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM paper_embeddings")
            embedded = cur.fetchone()[0]
            cur.execute(
                """
                SELECT COUNT(*) FROM papers p
                WHERE NOT EXISTS (
                    SELECT 1 FROM paper_embeddings pe WHERE pe.paper_id = p.id
                )
                """
            )
            to_delete = cur.fetchone()[0]

            print(f"Papers: {papers_before}, embedded: {embedded}, do usunięcia: {to_delete}")

            if args.dry_run or to_delete == 0:
                return 0

            cur.execute(
                """
                DELETE FROM papers p
                WHERE NOT EXISTS (
                    SELECT 1 FROM paper_embeddings pe WHERE pe.paper_id = p.id
                )
                """
            )
            deleted = cur.rowcount
            conn.commit()

            cur.execute("SELECT COUNT(*) FROM papers")
            papers_after = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM chunks")
            chunks_after = cur.fetchone()[0]
            cur.execute("ANALYZE papers")
            cur.execute("ANALYZE chunks")
            conn.commit()

    print(f"Usunięto papers: {deleted}")
    print(f"Zostało papers: {papers_after}, chunks: {chunks_after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
