"""Baseline 0 — naiwny chunk, vector only (+ title/summary prefilter). Bez FTS/anchor/keywords."""
from __future__ import annotations

import time

from psycopg import Connection

from app.config import HIERARCHICAL_PAPER_LIMIT, HYBRID_CANDIDATE_MULTIPLIER, llm_context_limit
from app.schemas import SearchHitV2
from app.services.embeddings import embed_text, to_vector_literal
from app.services.metadata_filters import MetadataFilters


def _row_to_hit(row) -> SearchHitV2:
    vector_distance = float(row[6])
    score = max(0.0, 1.0 - min(vector_distance, 1.0))
    chunk_id = row[0]
    content = row[5]
    return SearchHitV2(
        child_id=chunk_id,
        parent_id=chunk_id,
        paper_id=row[1],
        arxiv_id=row[2],
        title=row[3],
        arxiv_url=row[4],
        section_name=None,
        subsection_name=None,
        child_snippet=content[:400],
        content=content,
        vector_distance=vector_distance,
        text_score=0.0,
        hybrid_score=score,
        rerank_score=None,
        score=score,
    )


async def search_baseline0_vector(
    conn: Connection,
    semantic_query: str,
    top_k: int,
    *,
    metadata_filters: MetadataFilters | None = None,
    timings: dict[str, float] | None = None,
) -> list[SearchHitV2]:
    t_embed = time.perf_counter()
    query_embedding = await embed_text(semantic_query)
    if timings is not None:
        timings["embed_ms"] = round((time.perf_counter() - t_embed) * 1000, 1)
    vec = to_vector_literal(query_embedding)
    limit = max(top_k * HYBRID_CANDIDATE_MULTIPLIER, llm_context_limit(top_k))
    meta_sql, meta_params = (
        metadata_filters.sql_and("p") if metadata_filters else ("", [])
    )

    chunk_sql = f"""
        SELECT
            b.id::text,
            p.id::text,
            p.arxiv_id,
            p.title,
            p.arxiv_url,
            b.content,
            (b.embedding <=> %s::vector) AS vector_distance
        FROM baseline0_chunks b
        INNER JOIN papers p ON p.id = b.paper_id
        WHERE b.embedding IS NOT NULL
        {meta_sql}
        ORDER BY b.embedding <=> %s::vector
        LIMIT %s
    """

    with conn.cursor() as cur:
        cur.execute("SET LOCAL max_parallel_workers_per_gather = 0")
        t_sql = time.perf_counter()
        cur.execute(chunk_sql, (vec, *meta_params, vec, limit))
        global_rows = cur.fetchall()

        cur.execute(
            f"""
            SELECT pe.paper_id::text
            FROM paper_embeddings pe
            INNER JOIN papers p ON p.id = pe.paper_id
            WHERE pe.title_embedding IS NOT NULL OR pe.summary_embedding IS NOT NULL
            {meta_sql}
            ORDER BY LEAST(
                COALESCE(pe.title_embedding <=> %s::vector, 2.0),
                COALESCE(pe.summary_embedding <=> %s::vector, 2.0)
            )
            LIMIT %s
            """,
            (*meta_params, vec, vec, HIERARCHICAL_PAPER_LIMIT),
        )
        paper_ids = [r[0] for r in cur.fetchall()]

        paper_rows: list = []
        if paper_ids:
            cur.execute(
                f"""
                SELECT
                    b.id::text,
                    p.id::text,
                    p.arxiv_id,
                    p.title,
                    p.arxiv_url,
                    b.content,
                    (b.embedding <=> %s::vector) AS vector_distance
                FROM baseline0_chunks b
                INNER JOIN papers p ON p.id = b.paper_id
                WHERE b.embedding IS NOT NULL
                  AND b.paper_id = ANY(%s::uuid[])
                {meta_sql}
                ORDER BY b.embedding <=> %s::vector
                LIMIT %s
                """,
                (vec, paper_ids, *meta_params, vec, limit),
            )
            paper_rows = cur.fetchall()

    if timings is not None:
        timings["sql_ms"] = round((time.perf_counter() - t_sql) * 1000, 1)

    merged: dict[str, SearchHitV2] = {}
    for row in paper_rows + global_rows:
        hit = _row_to_hit(row)
        prev = merged.get(hit.child_id)
        if prev is None or hit.hybrid_score > prev.hybrid_score:
            merged[hit.child_id] = hit

    hits = sorted(merged.values(), key=lambda h: h.hybrid_score, reverse=True)[
        :limit
    ]
    return hits[: llm_context_limit(top_k)]
