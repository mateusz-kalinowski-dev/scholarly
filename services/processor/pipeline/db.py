"""Operacje Postgres (parent-child chunks, ParadeDB)."""
from __future__ import annotations

import logging

import redis
from psycopg import connect

from arxiv_ids import normalize_arxiv_id

from .chunking import ChildChunkDraft, ParentChunkDraft
from config import (
    POSTGRES_URL,
    REDIS_URL,
    SEARCH_INDEX_COUNTER_KEY,
    SEARCH_INDEX_EVERY_N_PAPERS,
)
from .sanitize import sanitize_db_text

logger = logging.getLogger(__name__)
_redis = redis.from_url(REDIS_URL, decode_responses=True)


def _to_vector(values: list[float]) -> str:
    return "[" + ",".join(str(v) for v in values) + "]"


def paper_is_fully_processed(arxiv_id: str) -> bool:
    base_id = normalize_arxiv_id(arxiv_id)
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT embedding_status FROM papers WHERE arxiv_id = %s",
                (base_id,),
            )
            row = cur.fetchone()
    return bool(row and row[0] == "DONE")


def paper_is_skipped(arxiv_id: str) -> bool:
    """Trwały brak źródła (parsing FAILED) — nie przetwarzaj ponownie."""
    base_id = normalize_arxiv_id(arxiv_id)
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT parsing_status FROM papers WHERE arxiv_id = %s",
                (base_id,),
            )
            row = cur.fetchone()
    return bool(row and row[0] == "FAILED")


def upsert_paper_metadata(data: dict) -> tuple[str, str, bool] | None:
    """
    Zwraca (paper_uuid, arxiv_id, should_process).
    should_process=False gdy praca już ma embedding_status=DONE.
    """
    arxiv_id = normalize_arxiv_id(data["id"])
    if paper_is_fully_processed(arxiv_id):
        return None
    if paper_is_skipped(arxiv_id):
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


def update_paper_after_ingest(arxiv_id: str, storage_path: str) -> None:
    base_id = normalize_arxiv_id(arxiv_id)
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE papers SET
                    storage_path = %s,
                    parsing_status = 'PARSED'
                WHERE arxiv_id = %s
                """,
                (storage_path, base_id),
            )
            conn.commit()


def mark_failed(arxiv_id: str, stage: str) -> None:
    base_id = normalize_arxiv_id(arxiv_id)
    column = {
        "parsing": "parsing_status",
        "chunking": "chunking_status",
        "embedding": "embedding_status",
    }.get(stage, "parsing_status")
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE papers SET {column} = 'FAILED' WHERE arxiv_id = %s",
                (base_id,),
            )
            conn.commit()


def mark_source_unavailable(arxiv_id: str) -> None:
    """Brak PDF/e-print — nie retry, scraper też pomija."""
    base_id = normalize_arxiv_id(arxiv_id)
    with connect(POSTGRES_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE papers SET
                    parsing_status = 'FAILED',
                    chunking_status = 'FAILED',
                    embedding_status = 'FAILED'
                WHERE arxiv_id = %s
                """,
                (base_id,),
            )
            conn.commit()


def maybe_refresh_search_indexes() -> None:
    """Co N ukończonych prac — CREATE INDEX IF NOT EXISTS (HNSW/GIN/BM25)."""
    count = _redis.incr(SEARCH_INDEX_COUNTER_KEY)
    if count < SEARCH_INDEX_EVERY_N_PAPERS:
        logger.debug(
            "Indeksy: %s/%s prac od ostatniego odświeżenia",
            count,
            SEARCH_INDEX_EVERY_N_PAPERS,
        )
        return

    _redis.set(SEARCH_INDEX_COUNTER_KEY, 0)
    logger.info(
        "Indeksy: próg %s prac — buduję HNSW/GIN/BM25 (IF NOT EXISTS)",
        SEARCH_INDEX_EVERY_N_PAPERS,
    )
    try:
        build_search_indexes()
    except Exception as e:
        logger.warning("Budowanie indeksów nieudane: %s", e)


def get_paper_for_rechunk(arxiv_id: str) -> dict | None:
    with connect(POSTGRES_URL) as conn:
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
    with connect(POSTGRES_URL) as conn:
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
    with connect(POSTGRES_URL) as conn:
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
    with connect(POSTGRES_URL) as conn:
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
    with connect(POSTGRES_URL) as conn:
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
    with connect(POSTGRES_URL) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            for sql in _FTS_INDEX_DROPS:
                cur.execute(sql)
            cur.execute("ALTER TABLE chunks DISABLE TRIGGER chunks_text_search_trg")


def restore_keywords_backfill_triggers() -> None:
    """Włącza trigger po backfillu (indeksy: rebuild_indexes.py)."""
    with connect(POSTGRES_URL) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("ALTER TABLE chunks ENABLE TRIGGER chunks_text_search_trg")


def refresh_child_text_search() -> int:
    """Przelicza search_text + text_search dla wszystkich child (trigger)."""
    with connect(POSTGRES_URL) as conn:
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
    with connect(POSTGRES_URL) as conn:
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
    with connect(POSTGRES_URL) as conn:
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
