"""Operacje Postgres dla pipeline RAG."""
from __future__ import annotations

from psycopg import connect

from chunking import TextChunk
from config import POSTGRES_URL


def _to_vector(values: list[float]) -> str:
    return "[" + ",".join(str(v) for v in values) + "]"


def paper_is_fully_processed(arxiv_id: str) -> bool:
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT embedding_status FROM papers
                WHERE arxiv_id = %s
                """,
                (arxiv_id,),
            )
            row = cur.fetchone()
    return bool(row and row[0] == "DONE")


def upsert_paper_metadata(data: dict) -> tuple[str, str, bool] | None:
    """
    Zwraca (paper_uuid, arxiv_id, should_process).
    should_process=False gdy praca już ma embedding_status=DONE (bez MinIO/pipeline).
    """
    arxiv_id = data["id"]
    if paper_is_fully_processed(arxiv_id):
        return None

    arxiv_url = data.get("arxiv_url") or f"https://arxiv.org/abs/{arxiv_id}"
    pdf_url = data.get("pdf_url") or f"https://arxiv.org/pdf/{arxiv_id}"

    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id::text, embedding_status FROM papers WHERE arxiv_id = %s
                """,
                (arxiv_id,),
            )
            existing = cur.fetchone()

            if existing and existing[1] == "DONE":
                return existing[0], arxiv_id, False

            cur.execute(
                """
                INSERT INTO papers (
                    arxiv_id, arxiv_url, pdf_url, title, summary,
                    published_at, updated_at, primary_category,
                    categories, authors,
                    parsing_status, chunking_status, embedding_status
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    'PROCESSING', 'PENDING', 'PENDING'
                )
                ON CONFLICT (arxiv_id) DO UPDATE SET
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    updated_at = EXCLUDED.updated_at,
                    categories = EXCLUDED.categories,
                    authors = EXCLUDED.authors
                WHERE papers.embedding_status IS DISTINCT FROM 'DONE'
                RETURNING id::text, embedding_status
                """,
                (
                    arxiv_id,
                    arxiv_url,
                    pdf_url,
                    data["title"],
                    data.get("summary_raw") or data.get("summary"),
                    data.get("published"),
                    data.get("updated") or data.get("published"),
                    data.get("primary_category"),
                    data.get("categories") or [],
                    data.get("authors") or [],
                ),
            )
            row = cur.fetchone()
            conn.commit()
            if not row:
                return None
            return row[0], arxiv_id, row[1] != "DONE"


def update_paper_after_ingest(
    arxiv_id: str, storage_path: str, paper_token_count: int
) -> None:
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE papers SET
                    storage_path = %s,
                    paper_token_count = %s,
                    parsing_status = 'PARSED'
                WHERE arxiv_id = %s
                """,
                (storage_path, paper_token_count, arxiv_id),
            )
            conn.commit()


def save_chunks(paper_id: str, chunks: list[TextChunk]) -> list[str]:
    """Usuwa stare chunki i wstawia nowe; zwraca listę UUID chunków."""
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE paper_id = %s::uuid", (paper_id,))
            chunk_ids: list[str] = []
            for ch in chunks:
                cur.execute(
                    """
                    INSERT INTO chunks (
                        paper_id, section_name, subsection_name,
                        chunk_index, token_count, content
                    )
                    VALUES (%s::uuid, %s, %s, %s, %s, %s)
                    RETURNING id::text
                    """,
                    (
                        paper_id,
                        ch.section_name,
                        ch.subsection_name,
                        ch.chunk_index,
                        ch.token_count,
                        ch.content,
                    ),
                )
                chunk_ids.append(cur.fetchone()[0])

            cur.execute(
                """
                UPDATE papers SET
                    chunking_status = 'DONE',
                    paper_token_count = %s
                WHERE id = %s::uuid
                """,
                (
                    sum(c.token_count for c in chunks),
                    paper_id,
                ),
            )
            conn.commit()
            return chunk_ids


def update_chunk_embeddings_bulk(pairs: list[tuple[str, list[float]]]) -> None:
    """Jeden commit dla wszystkich wektorów chunków."""
    if not pairs:
        return
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                UPDATE chunks SET embedding = %s::vector
                WHERE id = %s::uuid
                """,
                [(_to_vector(emb), cid) for cid, emb in pairs],
            )
            conn.commit()


def save_paper_embeddings(
    paper_id: str,
    title: str,
    summary: str | None,
    title_embedding: list[float],
    summary_embedding: list[float] | None,
) -> None:
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO paper_embeddings (
                    paper_id, title_embedding, summary_embedding
                )
                VALUES (%s::uuid, %s::vector, %s::vector)
                ON CONFLICT (paper_id) DO UPDATE SET
                    title_embedding = EXCLUDED.title_embedding,
                    summary_embedding = EXCLUDED.summary_embedding,
                    created_at = NOW()
                """,
                (
                    paper_id,
                    _to_vector(title_embedding),
                    _to_vector(summary_embedding) if summary_embedding else None,
                ),
            )
            cur.execute(
                """
                UPDATE papers SET embedding_status = 'DONE'
                WHERE id = %s::uuid
                """,
                (paper_id,),
            )
            conn.commit()


def mark_failed(arxiv_id: str, stage: str) -> None:
    column = {
        "parsing": "parsing_status",
        "chunking": "chunking_status",
        "embedding": "embedding_status",
    }.get(stage, "parsing_status")
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE papers SET {column} = 'FAILED' WHERE arxiv_id = %s",
                (arxiv_id,),
            )
            conn.commit()


def get_paper_fields(paper_id: str) -> dict | None:
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT title, summary FROM papers WHERE id = %s::uuid",
                (paper_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return {"title": row[0], "summary": row[1]}
