#!/usr/bin/env python3
"""
Migracja metadanych v1 → postgres_v2 (bez chunków — te powstaną w rechunk_v2).

Zachowuje UUID papers (legacy_paper_id) i golden_qa (legacy_chunk_id).
Źródła w MinIO pozostają bez zmian (storage_path).

Użycie:
  python scripts/migrate_metadata_v2.py
  POSTGRES_URL=... POSTGRES_V2_URL=... python scripts/migrate_metadata_v2.py
"""
from __future__ import annotations

import os
import sys

import psycopg
from dotenv import load_dotenv

load_dotenv()

OLD_URL = os.getenv(
    "POSTGRES_URL", "postgresql://admin:admin@localhost:5444/papers_db"
)
NEW_URL = os.getenv(
    "POSTGRES_V2_URL", "postgresql://admin:admin@localhost:5445/papers_db_v2"
)


def migrate_papers(old: psycopg.Connection, new: psycopg.Connection) -> int:
    with old.cursor() as cur:
        cur.execute(
            """
            SELECT id, arxiv_id, arxiv_url, pdf_url, title, summary,
                   published_at, updated_at, primary_category, categories,
                   authors, storage_path, source,
                   parsing_status, chunking_status, embedding_status,
                   paper_token_count, paper_page_count, created_at
            FROM papers
            ORDER BY created_at
            """
        )
        rows = cur.fetchall()

    inserted = 0
    with new.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO papers (
                    id, arxiv_id, arxiv_url, pdf_url, title, summary,
                    published_at, updated_at, primary_category, categories,
                    authors, storage_path, source,
                    parsing_status, chunking_status, embedding_status,
                    paper_token_count, paper_page_count,
                    schema_version, legacy_paper_id, created_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, 'PENDING', %s, %s,
                    'v2', %s, %s
                )
                ON CONFLICT (arxiv_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    storage_path = COALESCE(EXCLUDED.storage_path, papers.storage_path),
                    updated_at = EXCLUDED.updated_at,
                    categories = EXCLUDED.categories,
                    authors = EXCLUDED.authors
                """,
                (
                    row[0], row[1], row[2], row[3], row[4], row[5],
                    row[6], row[7], row[8], row[9], row[10], row[11], row[12],
                    row[13], row[14], row[16], row[17],
                    row[0], row[18],
                ),
            )
            inserted += 1
        new.commit()
    return inserted


def migrate_golden_qa(old: psycopg.Connection, new: psycopg.Connection) -> int:
    with old.cursor() as cur:
        cur.execute(
            """
            SELECT id, chunk_id, paper_id, arxiv_id, paper_title,
                   primary_category, section_name, question, ground_truth,
                   reference_context, question_type, generator_model,
                   generation_status, created_at
            FROM golden_qa
            """
        )
        rows = cur.fetchall()

    count = 0
    with new.cursor() as cur:
        for row in rows:
            cur.execute(
                """
                INSERT INTO golden_qa (
                    id, chunk_id, paper_id, arxiv_id, paper_title,
                    primary_category, section_name, question, ground_truth,
                    reference_context, question_type, generator_model,
                    generation_status, legacy_chunk_id, migration_status,
                    created_at
                )
                VALUES (
                    %s, NULL, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, 'pending', %s
                )
                ON CONFLICT (id) DO UPDATE SET
                    migration_status = 'pending',
                    legacy_chunk_id = EXCLUDED.legacy_chunk_id
                """,
                (
                    row[0], row[2], row[3], row[4], row[5], row[6],
                    row[7], row[8], row[9], row[10], row[11], row[12],
                    row[1], row[13],
                ),
            )
            count += cur.rowcount
        new.commit()
    return count


def main() -> int:
    print(f"Źródło:  {OLD_URL.split('@')[-1]}")
    print(f"Cel:     {NEW_URL.split('@')[-1]}")

    with psycopg.connect(OLD_URL) as old_conn, psycopg.connect(NEW_URL) as new_conn:
        n_papers = migrate_papers(old_conn, new_conn)
        n_golden = migrate_golden_qa(old_conn, new_conn)

    print(f"Zmigrowano papers: {n_papers}")
    print(f"Zmigrowano golden_qa: {n_golden} (chunk_id uzupełnisz po rechunk)")
    print("Następny krok: cd services/processor && python rechunk_v2.py --limit N")
    return 0


if __name__ == "__main__":
    sys.exit(main())
