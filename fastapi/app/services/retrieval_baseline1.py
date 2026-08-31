"""Baseline 1 — parent-child, prosty wektor (chunki + title/summary), bez FTS/rerank."""
from __future__ import annotations

import time

from psycopg import Connection

from app.config import (
    HIERARCHICAL_PAPER_LIMIT,
    HYBRID_CANDIDATE_MULTIPLIER,
    llm_context_limit,
)
from app.schemas import SearchHitV2
from app.services.embeddings import embed_text, to_vector_literal
from app.services.metadata_filters import MetadataFilters
from app.services.retrieval_v2 import collapse_children_to_parents


def _child_row_to_hit(row) -> SearchHitV2:
    vector_distance = float(row[10])
    score = max(0.0, 1.0 - min(vector_distance, 1.0))
    return SearchHitV2(
        child_id=row[0],
        parent_id=row[1],
        paper_id=row[2],
        arxiv_id=row[3],
        title=row[4],
        arxiv_url=row[5],
        section_name=row[6],
        subsection_name=row[7],
        child_snippet=row[8],
        content=row[9],
        vector_distance=vector_distance,
        text_score=0.0,
        hybrid_score=score,
        rerank_score=None,
        score=score,
    )


_CHILD_SELECT = """
    SELECT
        ch.id::text AS child_id,
        ch.parent_id::text AS parent_id,
        p.id::text AS paper_id,
        p.arxiv_id,
        p.title,
        p.arxiv_url,
        ch.section_name,
        ch.subsection_name,
        ch.content AS child_snippet,
        pa.content AS parent_content,
        (ch.embedding <=> %s::vector) AS vector_distance
    FROM chunks ch
    INNER JOIN chunks pa ON pa.id = ch.parent_id AND pa.chunk_role = 'parent'
    INNER JOIN papers p ON p.id = ch.paper_id
    WHERE ch.chunk_role = 'child'
      AND ch.embedding IS NOT NULL
      AND ch.parent_id IS NOT NULL
"""


async def search_baseline1_vector(
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
    child_limit = max(top_k * HYBRID_CANDIDATE_MULTIPLIER, llm_context_limit(top_k))
    meta_sql, meta_params = (
        metadata_filters.sql_and("p") if metadata_filters else ("", [])
    )

    with conn.cursor() as cur:
        cur.execute("SET LOCAL max_parallel_workers_per_gather = 0")

        t_sql = time.perf_counter()
        cur.execute(
            f"""
            {_CHILD_SELECT}
            {meta_sql}
            ORDER BY ch.embedding <=> %s::vector
            LIMIT %s
            """,
            (vec, *meta_params, vec, child_limit),
        )
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
                {_CHILD_SELECT}
                  AND ch.paper_id = ANY(%s::uuid[])
                {meta_sql}
                ORDER BY ch.embedding <=> %s::vector
                LIMIT %s
                """,
                (vec, paper_ids, *meta_params, vec, child_limit),
            )
            paper_rows = cur.fetchall()

    if timings is not None:
        timings["sql_ms"] = round((time.perf_counter() - t_sql) * 1000, 1)

    merged: dict[str, SearchHitV2] = {}
    for row in paper_rows + global_rows:
        hit = _child_row_to_hit(row)
        prev = merged.get(hit.child_id)
        if prev is None or hit.hybrid_score > prev.hybrid_score:
            merged[hit.child_id] = hit

    children = sorted(merged.values(), key=lambda h: h.hybrid_score, reverse=True)[
        :child_limit
    ]
    parents = collapse_children_to_parents(children)
    return parents[: llm_context_limit(top_k)]
