"""Operacje Postgres v2 (parent-child chunks)."""
from __future__ import annotations

from psycopg import connect

from .chunking import ChildChunkDraft, ParentChunkDraft
from .config import POSTGRES_V2_URL
from .sanitize import sanitize_db_text


def _to_vector(values: list[float]) -> str:
    return "[" + ",".join(str(v) for v in values) + "]"


def get_paper_for_rechunk(arxiv_id: str) -> dict | None:
    with connect(POSTGRES_V2_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id::text, arxiv_id, title, summary, storage_path
                FROM papers
                WHERE arxiv_id = %s AND storage_path IS NOT NULL
                """,
                (arxiv_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cols = [d.name for d in cur.description]
            return dict(zip(cols, row))


def save_parent_child_chunks(
    paper_id: str,
    parents: list[ParentChunkDraft],
) -> tuple[int, int]:
    """Zapisuje rodziców i dzieci; zwraca (liczba_parent, liczba_child)."""
    with connect(POSTGRES_V2_URL) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM chunks WHERE paper_id = %s::uuid", (paper_id,))
            parent_count = 0
            child_count = 0

            for parent in parents:
                cur.execute(
                    """
                    INSERT INTO chunks (
                        paper_id, chunk_role, section_name, subsection_name,
                        chunk_index, token_count, content, keywords, strategy
                    )
                    VALUES (%s::uuid, 'parent', %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id::text
                    """,
                    (
                        paper_id,
                        parent.section_name,
                        parent.subsection_name,
                        parent.chunk_index,
                        parent.token_count,
                        sanitize_db_text(parent.content),
                        [],
                        parent.strategy,
                    ),
                )
                parent_id = cur.fetchone()[0]
                parent_count += 1

                for child in parent.children:
                    cur.execute(
                        """
                        INSERT INTO chunks (
                            paper_id, parent_id, chunk_role, section_name,
                            subsection_name, chunk_index, child_index, sacred_type,
                            token_count, content, keywords, strategy
                        )
                        VALUES (
                            %s::uuid, %s::uuid, 'child', %s, %s, %s, %s, %s,
                            %s, %s, %s, %s
                        )
                        RETURNING id::text
                        """,
                        (
                            paper_id,
                            parent_id,
                            parent.section_name,
                            parent.subsection_name,
                            parent.chunk_index,
                            child.child_index,
                            child.sacred_type,
                            child.token_count,
                            sanitize_db_text(child.content),
                            [sanitize_db_text(k) for k in child.keywords if k],
                            parent.strategy,
                        ),
                    )
                    child_count += 1

            total_tokens = sum(p.token_count for p in parents)
            cur.execute(
                """
                UPDATE papers SET
                    chunking_status = 'DONE',
                    parsing_status = 'PARSED',
                    paper_token_count = %s
                WHERE id = %s::uuid
                """,
                (total_tokens, paper_id),
            )
            conn.commit()
    return parent_count, child_count


def list_child_contents(paper_id: str) -> list[tuple[str, str]]:
    with connect(POSTGRES_V2_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id::text, content FROM chunks
                WHERE paper_id = %s::uuid AND chunk_role = 'child'
                ORDER BY chunk_index, child_index
                """,
                (paper_id,),
            )
            return [(r[0], r[1]) for r in cur.fetchall()]


def update_child_embeddings(pairs: list[tuple[str, list[float]]]) -> None:
    if not pairs:
        return
    with connect(POSTGRES_V2_URL) as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                UPDATE chunks SET embedding = %s::vector
                WHERE id = %s::uuid AND chunk_role = 'child'
                """,
                [(_to_vector(emb), cid) for cid, emb in pairs],
            )
            conn.commit()


def update_paper_embeddings(
    paper_id: str,
    title_embedding: list[float],
    summary_embedding: list[float] | None,
    embed_model: str,
) -> None:
    with connect(POSTGRES_V2_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO paper_embeddings (
                    paper_id, title_embedding, summary_embedding, embed_model
                )
                VALUES (%s::uuid, %s::vector, %s::vector, %s)
                ON CONFLICT (paper_id) DO UPDATE SET
                    title_embedding = EXCLUDED.title_embedding,
                    summary_embedding = EXCLUDED.summary_embedding,
                    embed_model = EXCLUDED.embed_model,
                    created_at = NOW()
                """,
                (
                    paper_id,
                    _to_vector(title_embedding),
                    _to_vector(summary_embedding) if summary_embedding else None,
                    embed_model,
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


_FTS_INDEX_DROPS = (
    "DROP INDEX IF EXISTS chunks_child_text_search_gin_idx",
    "DROP INDEX IF EXISTS chunks_bm25_idx",
)


def prepare_keywords_backfill_fast() -> None:
    """DROP GIN/BM25 + wyłącz trigger — przyspiesza masowy UPDATE keywords."""
    with connect(POSTGRES_V2_URL) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            for sql in _FTS_INDEX_DROPS:
                cur.execute(sql)
            cur.execute("ALTER TABLE chunks DISABLE TRIGGER chunks_text_search_trg")


def restore_keywords_backfill_triggers() -> None:
    """Włącza trigger po backfillu (indeksy: rebuild_indexes_v2.py)."""
    with connect(POSTGRES_V2_URL) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE chunks ENABLE TRIGGER chunks_text_search_trg")


def refresh_child_text_search() -> int:
    """Przelicza search_text + text_search dla wszystkich child (trigger)."""
    with connect(POSTGRES_V2_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE chunks
                SET keywords = keywords
                WHERE chunk_role = 'child'
                """
            )
            n = cur.rowcount
            conn.commit()
    return n


def rebuild_search_indexes() -> None:
    """DROP + CREATE HNSW, GIN, BM25 na pełnym korpusie."""
    drops = [
        "DROP INDEX IF EXISTS chunks_child_embedding_hnsw_idx",
        "DROP INDEX IF EXISTS chunks_child_text_search_gin_idx",
        "DROP INDEX IF EXISTS chunks_bm25_idx",
    ]
    creates = [
        """
        CREATE INDEX chunks_child_embedding_hnsw_idx
        ON chunks USING hnsw (embedding vector_cosine_ops)
        WHERE chunk_role = 'child' AND embedding IS NOT NULL
        """,
        """
        CREATE INDEX chunks_child_text_search_gin_idx
        ON chunks USING gin (text_search)
        WHERE chunk_role = 'child'
        """,
        """
        CREATE INDEX chunks_bm25_idx ON chunks
        USING bm25 (id, content, search_text)
        WITH (key_field='id')
        """,
    ]
    with connect(POSTGRES_V2_URL) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET max_parallel_workers_per_gather = 0")
            for sql in drops:
                cur.execute(sql)
            for sql in creates:
                cur.execute(sql)


def build_search_indexes() -> None:
    """HNSW + GIN + BM25 — CREATE IF NOT EXISTS (pierwsze zasilenie)."""
    statements = [
        """
        CREATE INDEX IF NOT EXISTS chunks_child_embedding_hnsw_idx
        ON chunks USING hnsw (embedding vector_cosine_ops)
        WHERE chunk_role = 'child' AND embedding IS NOT NULL
        """,
        """
        CREATE INDEX IF NOT EXISTS chunks_child_text_search_gin_idx
        ON chunks USING gin (text_search)
        WHERE chunk_role = 'child'
        """,
    ]
    with connect(POSTGRES_V2_URL) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET max_parallel_workers_per_gather = 0")
            for sql in statements:
                cur.execute(sql)
            cur.execute(
                "SELECT 1 FROM pg_indexes WHERE indexname = 'chunks_bm25_idx'"
            )
            if not cur.fetchone():
                cur.execute(
                    """
                    CREATE INDEX chunks_bm25_idx ON chunks
                    USING bm25 (id, content, search_text)
                    WITH (key_field='id')
                    """
                )
