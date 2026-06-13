"""Diagnostyka retrieval dla pytania EUVP (golden chunk vs pgvector)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "fastapi"))

from app.services.embeddings import embed_text, to_vector_literal  # noqa: E402

QUESTION = (
    "Based on the experimental results on the EUVP dataset, how do the performance "
    "gains and energy costs of increasing the time steps (T) from 1 to 4 compare "
    "to those of increasing the quantisation steps (Q) from 1 to 4?"
)

GOLDEN_CHUNK_ID = "6ef72f56-e811-4886-982a-bc4c045804fa"
ARXIV_UIESNN = "2605.08376"

POSTGRES_URL = os.getenv(
    "POSTGRES_URL", "postgresql://admin:admin@localhost:5444/papers_db"
)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")


async def main() -> None:
    print("=== Diagnostyka retrieval (EUVP) ===\n")
    print(f"Postgres: {POSTGRES_URL.split('@')[-1]}")
    print(f"Ollama:   {OLLAMA_BASE_URL} model={EMBED_MODEL}\n")

    with psycopg.connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM chunks WHERE embedding IS NOT NULL")
            n_emb = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM chunks")
            n_all = cur.fetchone()[0]
            print(f"Chunki w DB: {n_all} total, {n_emb} z embeddingiem")

            cur.execute(
                """
                SELECT COUNT(*) FROM chunks c
                JOIN papers p ON p.id = c.paper_id
                WHERE c.content ILIKE %s AND c.embedding IS NOT NULL
                """,
                ("%EUVP%",),
            )
            n_euvp = cur.fetchone()[0]
            print(f"Chunki z 'EUVP' w treści (z embed): {n_euvp}\n")

            cur.execute(
                """
                SELECT c.id::text, p.arxiv_id, p.title,
                       LEFT(c.content, 200), c.token_count,
                       c.section_name
                FROM chunks c
                JOIN papers p ON p.id = c.paper_id
                WHERE c.id = %s::uuid
                """,
                (GOLDEN_CHUNK_ID,),
            )
            golden = cur.fetchone()
            if not golden:
                print(f"GOLDEN chunk {GOLDEN_CHUNK_ID} NIE ISTNIEJE w chunks!")
            else:
                print("Golden chunk:")
                print(f"  id:      {golden[0]}")
                print(f"  arxiv:   {golden[1]}")
                print(f"  title:   {golden[2][:80]}...")
                print(f"  section: {golden[5]}")
                print(f"  tokens:  {golden[4]}")
                print(f"  preview: {golden[3]}...")
                cur.execute(
                    "SELECT embedding IS NOT NULL FROM chunks WHERE id = %s::uuid",
                    (GOLDEN_CHUNK_ID,),
                )
                has_emb = cur.fetchone()[0]
                print(f"  embedding: {'TAK' if has_emb else 'BRAK'}\n")

            cur.execute(
                """
                SELECT c.id::text, c.chunk_index, LEFT(c.content, 120)
                FROM chunks c
                JOIN papers p ON p.id = c.paper_id
                WHERE p.arxiv_id = %s
                ORDER BY chunk_index
                """,
                (ARXIV_UIESNN,),
            )
            uiesnn = cur.fetchall()
            print(f"UIESNN ({ARXIV_UIESNN}): {len(uiesnn)} chunków")
            for row in uiesnn[:8]:
                has_euvp = "EUVP" in (row[2] or "")
                print(f"  [{row[1]}] EUVP={'yes' if has_euvp else 'no '} {row[2][:100]}...")
            if len(uiesnn) > 8:
                print(f"  ... +{len(uiesnn) - 8} więcej\n")

    vec = to_vector_literal(await embed_text(QUESTION))
    print("Embedding pytania OK (dim sprawdzany w SQL)\n")

    for top_k in (10, 20, 50):
        with psycopg.connect(POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        c.id::text,
                        p.arxiv_id,
                        LEFT(p.title, 40),
                        LEFT(c.content, 80),
                        1 - (c.embedding <=> %s::vector) AS score,
                        (c.content ILIKE '%%EUVP%%') AS has_euvp
                    FROM chunks c
                    JOIN papers p ON p.id = c.paper_id
                    WHERE c.embedding IS NOT NULL
                    ORDER BY c.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (vec, vec, top_k),
                )
                rows = cur.fetchall()

        golden_rank = next(
            (i + 1 for i, r in enumerate(rows) if r[0] == GOLDEN_CHUNK_ID), None
        )
        euvp_in_top = sum(1 for r in rows if r[5])
        print(f"--- Top-{top_k} (cosine) ---")
        print(f"  Golden chunk rank: {golden_rank or 'POZA Top-K'}")
        print(f"  Wyników z 'EUVP' w treści: {euvp_in_top}/{len(rows)}")
        for i, r in enumerate(rows[:5], 1):
            mark = " *** GOLDEN" if r[0] == GOLDEN_CHUNK_ID else (" [EUVP]" if r[5] else "")
            print(f"  {i}. score={r[4]:.4f} {r[1]} {mark}")
            print(f"     {r[3]}...")

    # Rank golden chunk w całej bazie
    with psycopg.connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                WITH ranked AS (
                    SELECT c.id::text,
                           ROW_NUMBER() OVER (ORDER BY c.embedding <=> %s::vector) AS rn,
                           1 - (c.embedding <=> %s::vector) AS score
                    FROM chunks c
                    WHERE c.embedding IS NOT NULL
                )
                SELECT rn, score FROM ranked WHERE id = %s
                """,
                (vec, vec, GOLDEN_CHUNK_ID),
            )
            gr = cur.fetchone()
            if gr:
                print(f"\nGlobalna pozycja golden chunk: #{gr[0]} / {n_emb} (score={gr[1]:.4f})")
            else:
                print("\nGolden chunk bez embeddingu — nie rankuje w vector search")

            # Keyword baseline
            cur.execute(
                """
                SELECT c.id::text, p.arxiv_id,
                       ts_rank_cd(to_tsvector('english', c.content),
                                  plainto_tsquery('english', 'EUVP time steps quantisation'))
                FROM chunks c
                JOIN papers p ON p.id = c.paper_id
                WHERE c.content ILIKE '%%EUVP%%'
                  AND (c.content ILIKE '%%time step%%' OR c.content ILIKE '%%quantisation%%'
                       OR c.content ILIKE '%%quantization%%')
                ORDER BY 3 DESC NULLS LAST
                LIMIT 5
                """,
            )
            kw = cur.fetchall()
            print("\nKeyword (EUVP + time/quant): top 5 chunk ids:")
            for row in kw:
                mark = " *** GOLDEN" if row[0] == GOLDEN_CHUNK_ID else ""
                print(f"  {row[0]} {row[1]}{mark}")

    # Czy golden embed podobny do samego pytania vs do losowego chunka AREA?
    async with httpx.AsyncClient(timeout=120.0) as client:
        with psycopg.connect(POSTGRES_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT content FROM chunks WHERE id = %s::uuid",
                    (GOLDEN_CHUNK_ID,),
                )
                golden_content = cur.fetchone()[0]
                cur.execute(
                    """
                    SELECT c.content FROM chunks c
                    JOIN papers p ON p.id = c.paper_id
                    WHERE c.embedding IS NOT NULL
                      AND p.arxiv_id != %s
                      AND c.content ILIKE '%%CIFAR%%'
                    LIMIT 1
                    """,
                    (ARXIV_UIESNN,),
                )
                wrong = cur.fetchone()

        for label, text in [
            ("question", QUESTION),
            ("golden_chunk", golden_content[:2000]),
            ("wrong_top_hit_sample", (wrong[0][:2000] if wrong else "")),
        ]:
            if not text:
                continue
            r = await client.post(
                f"{OLLAMA_BASE_URL}/api/embed",
                json={"model": EMBED_MODEL, "input": text[:8000]},
            )
            emb = r.json().get("embeddings", [None])[0]
            print(f"  {label}: dim={len(emb) if emb else 0}")


if __name__ == "__main__":
    asyncio.run(main())
