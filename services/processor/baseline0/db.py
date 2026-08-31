"""Postgres — tabela baseline0_chunks."""
from __future__ import annotations

from pathlib import Path

from psycopg import connect

from .config import POSTGRES_URL

_MIGRATION = Path(__file__).resolve().parent / "schema.sql"


def _to_vector(values: list[float]) -> str:
    return "[" + ",".join(str(v) for v in values) + "]"


def ensure_schema() -> None:
    sql = _MIGRATION.read_text(encoding="utf-8")
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def list_papers(*, limit: int | None = None, only_unprocessed: bool = False) -> list[dict]:
    q = """
        SELECT p.id::text, p.arxiv_id, p.storage_path
        FROM papers p
    """
    if only_unprocessed:
        q += """
        LEFT JOIN (
            SELECT DISTINCT paper_id
            FROM baseline0_chunks
        ) b0 ON b0.paper_id = p.id
        """
    q += """
        WHERE p.storage_path IS NOT NULL
          AND p.parsing_status IN ('DONE', 'PARSED')
    """
    if only_unprocessed:
        q += """
          AND b0.paper_id IS NULL
        """
    q += """
        ORDER BY p.arxiv_id
    """
    params: tuple = ()
    if limit is not None:
        q += " LIMIT %s"
        params = (limit,)
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(q, params)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


def clear_baseline0() -> None:
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE baseline0_chunks")
            cur.execute("DELETE FROM baseline0_meta")
        conn.commit()


def delete_paper_chunks(paper_id: str) -> None:
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM baseline0_chunks WHERE paper_id = %s::uuid",
                (paper_id,),
            )
        conn.commit()


def insert_chunks_batch(
    rows: list[tuple[str, int, str, list[float] | None]],
) -> int:
    """rows: (paper_id, chunk_index, content, embedding|None)"""
    if not rows:
        return 0
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO baseline0_chunks (
                    paper_id, chunk_index, char_count, content, embedding
                )
                VALUES (%s::uuid, %s, %s, %s, %s::vector)
                ON CONFLICT (paper_id, chunk_index) DO UPDATE SET
                    char_count = EXCLUDED.char_count,
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding
                """,
                [
                    (
                        paper_id,
                        idx,
                        len(content),
                        content,
                        _to_vector(emb) if emb is not None else None,
                    )
                    for paper_id, idx, content, emb in rows
                ],
            )
        conn.commit()
    return len(rows)


def save_meta(
    *,
    chunk_size: int,
    chunk_overlap: int,
    embed_model: str,
    embed_dim: int,
    papers_total: int,
    chunks_total: int,
) -> None:
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM baseline0_meta")
            cur.execute(
                """
                INSERT INTO baseline0_meta (
                    id, chunk_size, chunk_overlap, embed_model, embed_dim,
                    papers_total, chunks_total, built_at
                )
                VALUES (1, %s, %s, %s, %s, %s, %s, NOW())
                """,
                (
                    chunk_size,
                    chunk_overlap,
                    embed_model,
                    embed_dim,
                    papers_total,
                    chunks_total,
                ),
            )
        conn.commit()


def build_hnsw_index() -> None:
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM pg_indexes WHERE indexname = 'baseline0_chunks_embedding_hnsw_idx'"
            )
            if cur.fetchone():
                cur.execute("REINDEX INDEX baseline0_chunks_embedding_hnsw_idx")
            else:
                cur.execute(
                    """
                    CREATE INDEX baseline0_chunks_embedding_hnsw_idx
                    ON baseline0_chunks
                    USING hnsw (embedding vector_cosine_ops)
                    WITH (m = 16, ef_construction = 64)
                    """
                )
        conn.commit()


def count_chunks() -> int:
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM baseline0_chunks")
            return int(cur.fetchone()[0])
