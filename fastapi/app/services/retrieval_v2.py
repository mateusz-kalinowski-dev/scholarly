"""Hybrid retrieval v2: child vector + FTS → parent context."""
from __future__ import annotations

import re
import time
from typing import Literal

from psycopg import Connection

from app.config import (
    ANCHOR_HYBRID_BOOST,
    HYBRID_CANDIDATE_MULTIPLIER,
    HYBRID_RRF_K,
    hybrid_prefetch_limits,
)
from app.schemas import SearchHitV2
from app.services.embeddings import embed_text, to_vector_literal
from app.services.metadata_filters import MetadataFilters

FtsBackend = Literal["gin", "bm25"]

_ANCHOR_SKIP = frozenset(
    {
        "WHAT", "WHICH", "WHERE", "WHEN", "THAT", "THIS", "THESE", "THOSE", "HOW",
        "ACCORDING", "BASED", "GIVEN", "USING", "HOWEVER", "THEREFORE", "FURTHERMORE",
        "ADDITIONALLY", "SINCE", "WHILE", "ALTHOUGH", "FOLLOWING", "UNDER", "DURING",
        "WITHIN", "WITHOUT", "DESPITE", "UNLIKE", "TABLE", "FIGURE", "SECTION",
        "ABSTRACT", "INTRODUCTION", "METHODS", "RESULTS", "CONCLUSION", "OVERALL",
        "SPECIFICALLY", "TYPICALLY", "GENERALLY", "FINALLY", "FIRST", "SECOND", "THIRD",
    }
)


def _is_anchor_term(term: str) -> bool:
    """Prawdziwe encje (UIESNN, EUVP), nie zwykłe słowa z wielkiej litery (According)."""
    if term.upper() in _ANCHOR_SKIP:
        return False
    if term.isupper() and len(term) >= 2:
        return True
    if any(c.isdigit() for c in term):
        return True
    if re.search(r"[a-z][A-Z]|[A-Z][a-z].*[A-Z]", term):
        return True
    return False


def anchor_terms_from_text(text: str) -> list[str]:
    """Named entities / model names (UIESNN, SIGNAVOX, …)."""
    found: list[str] = []
    seen: set[str] = set()
    for pattern in (r"\b[A-Z][A-Za-z0-9-]{2,}\b", r"\b[A-Z]{2,}\d*\b"):
        for match in re.findall(pattern, text):
            if not _is_anchor_term(match):
                continue
            key = match.upper()
            if key in seen:
                continue
            seen.add(key)
            found.append(match)
    return found


def _sanitize_tsquery(query: str, *, exclude: set[str] | None = None) -> str:
    skip = {t.lower() for t in (exclude or ())}
    terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]{1,}", query)
    terms = [
        t
        for t in terms
        if len(t) > 2 and t.lower() not in skip
    ][:8]
    return " ".join(terms)


def _papers_join_if(meta_sql: str) -> str:
    """JOIN papers tylko gdy filtry metadanych wymagają aliasu p."""
    return "INNER JOIN papers p ON p.id = ch.paper_id" if meta_sql.strip() else ""


def _bm25_match_query(
    lexical_query: str,
    anchor_terms: list[str] | None = None,
    *,
    broad: bool = False,
) -> str:
    """Krótsze zapytanie BM25 — ParadeDB/Tantivy wolniej skaluje z długą frazą (3+ termy)."""
    skip = {
        "the", "and", "for", "with", "from", "mode", "compare", "performance",
        "versus", "how", "does", "its", "than", "into", "about",
    }
    terms: list[str] = []
    seen: set[str] = set()
    for term in anchor_terms or []:
        key = term.lower()
        if key not in seen:
            terms.append(term)
            seen.add(key)
    if broad:
        if terms:
            return " ".join(terms[:2])
        max_terms = 2
    else:
        max_terms = 6
    for term in re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]{1,}", lexical_query):
        key = term.lower()
        if len(term) <= 2 or key in skip or key in seen:
            continue
        terms.append(term)
        seen.add(key)
        if len(terms) >= max_terms:
            break
    return " ".join(terms) if terms else lexical_query[:120]


def _anchor_match_parts(
    term: str,
    *,
    fts_backend: FtsBackend,
    include_parent: bool,
) -> tuple[str, list[str]]:
    """Indeksowane FTS: GIN text_search lub BM25 search_text (+ tytuł papieru)."""
    params: list[str] = [term]
    parts = [
        "to_tsvector('english', coalesce(p.title, '')) @@ phraseto_tsquery('english', %s)"
    ]
    if fts_backend == "bm25":
        parts.append("ch.id @@@ paradedb.match('search_text', %s)")
        params.append(term)
        if include_parent:
            parts.append("pa.id @@@ paradedb.match('search_text', %s)")
            params.append(term)
    else:
        parts.append("ch.text_search @@ phraseto_tsquery('english', %s)")
        params.append(term)
        if include_parent:
            parts.append("pa.text_search @@ phraseto_tsquery('english', %s)")
            params.append(term)
    return f"({' OR '.join(parts)})", params


def _anchor_match_clause(
    anchor_terms: list[str],
    *,
    fts_backend: FtsBackend = "gin",
    include_parent: bool = True,
) -> tuple[str, list[str]]:
    if not anchor_terms:
        return "", []
    term_clauses: list[str] = []
    params: list[str] = []
    for term in anchor_terms:
        clause, clause_params = _anchor_match_parts(
            term, fts_backend=fts_backend, include_parent=include_parent
        )
        term_clauses.append(clause)
        params.extend(clause_params)
    return f"AND ({' OR '.join(term_clauses)})", params


def _anchor_boost_clause(
    anchor_terms: list[str],
    *,
    fts_backend: FtsBackend = "gin",
) -> tuple[str, list[str], float]:
    if not anchor_terms:
        return "0.0::float8", [], 0.0
    term_clauses: list[str] = []
    params: list[str] = []
    for term in anchor_terms:
        clause, clause_params = _anchor_match_parts(
            term, fts_backend=fts_backend, include_parent=True
        )
        term_clauses.append(clause)
        params.extend(clause_params)
    return (
        f"CASE WHEN ({' OR '.join(term_clauses)}) THEN %s ELSE 0.0 END",
        params,
        ANCHOR_HYBRID_BOOST,
    )


def _anchor_boost_broad(
    anchor_terms: list[str],
    *,
    fts_backend: FtsBackend,
    meta_sql: str,
    meta_params: list,
) -> tuple[str, str, tuple, tuple]:
    """
    Broad pass: boost SQL + opcjonalne CTE (BM25 nie używa @@@ w CASE WHEN).
    Zwraca (boost_cte_sql, boost_expr, boost_cte_params, scored_boost_params).
    """
    if not anchor_terms:
        return "", "0.0::float8", (), ()

    if fts_backend == "bm25":
        union_parts: list[str] = []
        cte_params: list = []
        for term in anchor_terms:
            union_parts.append(f"""
            SELECT ch.id
            FROM chunks ch
            INNER JOIN papers p ON p.id = ch.paper_id
            WHERE ch.chunk_role = 'child'
              AND to_tsvector('english', coalesce(p.title, ''))
                  @@ phraseto_tsquery('english', %s)
              {meta_sql}""")
            cte_params.extend([term, *meta_params])
        boost_cte = f"""
        anchor_boost_ids AS (
            SELECT DISTINCT id FROM (
                {" UNION ALL ".join(union_parts)}
            ) ab
        ),"""
        boost_expr = (
            "CASE WHEN ch.id IN (SELECT id FROM anchor_boost_ids) "
            "THEN %s ELSE 0.0 END"
        )
        return boost_cte, boost_expr, tuple(cte_params), (ANCHOR_HYBRID_BOOST,)

    boost_expr, boost_params, boost_weight = _anchor_boost_clause(
        anchor_terms, fts_backend="gin"
    )
    return "", boost_expr, (), (*boost_params, boost_weight)


def _anchor_title_filter_clause(anchor_terms: list[str]) -> tuple[str, list[str]]:
    """Dopasowanie tytułu przez FTS (GIN na papers.title), bez ILIKE."""
    if not anchor_terms:
        return "FALSE", []
    clauses = [
        "to_tsvector('english', coalesce(p.title, '')) @@ phraseto_tsquery('english', %s)"
        for _ in anchor_terms
    ]
    return f"({' OR '.join(clauses)})", list(anchor_terms)


def _anchor_fts_filter_clause(
    anchor_terms: list[str],
    *,
    fts_backend: FtsBackend,
) -> tuple[str, list[str]]:
    """Tylko indeksowany FTS na chunkach (bez tytułu)."""
    if not anchor_terms:
        return "FALSE", []
    clauses: list[str] = []
    params: list[str] = []
    for term in anchor_terms:
        if fts_backend == "bm25":
            clauses.append("ch.id @@@ paradedb.match('search_text', %s)")
        else:
            clauses.append("ch.text_search @@ phraseto_tsquery('english', %s)")
        params.append(term)
    return f"({' OR '.join(clauses)})", params


def _anchor_where_clause(
    anchor_terms: list[str],
    *,
    fts_backend: FtsBackend,
) -> tuple[str, list[str]]:
    """Szybki anchor: GIN text_search / BM25 search_text (+ tytuł papieru)."""
    if not anchor_terms:
        return "TRUE", []
    term_clauses: list[str] = []
    params: list[str] = []
    for term in anchor_terms:
        if fts_backend == "bm25":
            term_clauses.append(
                "(ch.id @@@ paradedb.match('search_text', %s) "
                "OR to_tsvector('english', coalesce(p.title, '')) @@ phraseto_tsquery('english', %s))"
            )
        else:
            term_clauses.append(
                "(ch.text_search @@ phraseto_tsquery('english', %s) "
                "OR to_tsvector('english', coalesce(p.title, '')) @@ phraseto_tsquery('english', %s))"
            )
        params.extend([term, term])
    return f"({' OR '.join(term_clauses)})", params


def _hits_from_rows(rows) -> list[SearchHitV2]:
    hits: list[SearchHitV2] = []
    for row in rows:
        vector_distance = float(row[10])
        text_score = float(row[11])
        hybrid_score = float(row[13])
        hits.append(
            SearchHitV2(
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
                text_score=text_score,
                hybrid_score=hybrid_score,
                rerank_score=None,
                score=hybrid_score,
            )
        )
    return hits


async def _search_anchor_pass(
    conn: Connection,
    query: str,
    anchor_terms: list[str],
    *,
    limit: int,
    metadata_filters: MetadataFilters | None,
    fts_backend: FtsBackend,
    timings: dict[str, float] | None,
) -> list[SearchHitV2]:
    """Anchor pass: vector + FTS (GIN/BM25) + tytuł → RRF, bez full-scan po content."""
    t_embed = time.perf_counter()
    query_embedding = await embed_text(query)
    if timings is not None:
        timings["embed_ms"] = round((time.perf_counter() - t_embed) * 1000, 1)
    vec = to_vector_literal(query_embedding)

    meta_sql, meta_params = (
        metadata_filters.sql_and("p") if metadata_filters else ("", [])
    )
    fts_k = max(limit * 4, 100)
    vector_k = fts_k
    title_k = fts_k
    rank_term = anchor_terms[0]
    rrf_k = HYBRID_RRF_K

    if fts_backend == "bm25":
        papers_join = _papers_join_if(meta_sql)
        if len(anchor_terms) == 1:
            fts_inner = f"""
                SELECT ch.id
                FROM chunks ch
                {papers_join}
                WHERE ch.chunk_role = 'child'
                  AND ch.id @@@ paradedb.match('search_text', %s)
                  {meta_sql}
                ORDER BY paradedb.score(ch.id) DESC
                LIMIT %s"""
            fts_inner_params: list = [anchor_terms[0], *meta_params, fts_k]
        else:
            # Postgres: ORDER BY/LIMIT w gałęzi UNION wymaga nawiasów
            # (inaczej: syntax error at or near "UNION").
            union_parts: list[str] = []
            fts_inner_params = []
            for term in anchor_terms:
                union_parts.append(f"""
                (SELECT ch.id
                FROM chunks ch
                {papers_join}
                WHERE ch.chunk_role = 'child'
                  AND ch.id @@@ paradedb.match('search_text', %s)
                  {meta_sql}
                ORDER BY paradedb.score(ch.id) DESC
                LIMIT %s)""")
                fts_inner_params.extend([term, *meta_params, fts_k])
            fts_inner = (
                f"SELECT DISTINCT id FROM ({' UNION ALL '.join(union_parts)}) u LIMIT %s"
            )
            fts_inner_params.append(fts_k)
        fts_hits_cte = f"""
        fts_hits AS (
            SELECT id, ROW_NUMBER() OVER () AS fts_rank
            FROM ({fts_inner}) f
        ),"""
        fts_cte_params = fts_inner_params
    else:
        fts_filter, fts_filter_params = _anchor_fts_filter_clause(
            anchor_terms, fts_backend=fts_backend
        )
        fts_hits_cte = f"""
        fts_hits AS (
            SELECT id, ROW_NUMBER() OVER () AS fts_rank
            FROM (
                SELECT ch.id
                FROM chunks ch
                INNER JOIN papers p ON p.id = ch.paper_id
                WHERE ch.chunk_role = 'child'
                  AND ch.embedding IS NOT NULL
                  AND ch.parent_id IS NOT NULL
                  AND ({fts_filter})
                  {meta_sql}
                ORDER BY ts_rank(
                    ch.text_search, phraseto_tsquery('english', %s)
                ) DESC
                LIMIT %s
            ) f
        ),"""
        fts_cte_params = [*fts_filter_params, *meta_params, rank_term, fts_k]

    title_rank_expr = (
        "ts_rank(to_tsvector('english', coalesce(p.title, '')), "
        "phraseto_tsquery('english', %s))"
    )
    title_filter, title_filter_params = _anchor_title_filter_clause(anchor_terms)
    anchor_papers_join = _papers_join_if(meta_sql)
    sql = f"""
    WITH
    vector_hits AS (
        SELECT id, ROW_NUMBER() OVER () AS vec_rank
        FROM (
            SELECT ch.id
            FROM chunks ch
            {anchor_papers_join}
            WHERE ch.chunk_role = 'child'
              AND ch.embedding IS NOT NULL
              AND ch.parent_id IS NOT NULL
              {meta_sql}
            ORDER BY ch.embedding <=> %s::vector
            LIMIT %s
        ) v
    ),
    {fts_hits_cte}
    title_hits AS (
        SELECT id, ROW_NUMBER() OVER () AS title_rank
        FROM (
            SELECT ch.id
            FROM chunks ch
            INNER JOIN papers p ON p.id = ch.paper_id
            WHERE ch.chunk_role = 'child'
              AND ({title_filter})
              {meta_sql}
            ORDER BY {title_rank_expr} DESC
            LIMIT %s
        ) t
    ),
    rrf_parts AS (
        SELECT id, 1.0 / ({rrf_k} + vec_rank) AS score FROM vector_hits
        UNION ALL
        SELECT id, 1.0 / ({rrf_k} + fts_rank) AS score FROM fts_hits
        UNION ALL
        SELECT id, 1.0 / ({rrf_k} + title_rank) AS score FROM title_hits
    ),
    candidates AS (
        SELECT id, SUM(score) AS rrf_score
        FROM rrf_parts
        GROUP BY id
    ),
    ranked AS (
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
            (ch.embedding <=> %s::vector) AS vector_distance,
            c.rrf_score AS text_score,
            0.0::float8 AS anchor_boost
        FROM candidates c
        INNER JOIN chunks ch ON ch.id = c.id
            AND ch.chunk_role = 'child'
            AND ch.embedding IS NOT NULL
            AND ch.parent_id IS NOT NULL
        INNER JOIN papers p ON p.id = ch.paper_id
        INNER JOIN chunks pa ON pa.id = ch.parent_id AND pa.chunk_role = 'parent'
    )
    SELECT
        child_id, parent_id, paper_id, arxiv_id, title, arxiv_url,
        section_name, subsection_name, child_snippet, parent_content,
        vector_distance, text_score, anchor_boost,
        text_score AS hybrid_score
    FROM ranked
    ORDER BY hybrid_score DESC, vector_distance ASC
    LIMIT %s
    """
    params = (
        *meta_params,
        vec,
        vector_k,
        *fts_cte_params,
        *title_filter_params,
        *meta_params,
        rank_term,
        title_k,
        vec,
        limit,
    )

    if timings is not None:
        timings["fts_backend"] = fts_backend  # type: ignore[assignment]

    with conn.cursor() as cur:
        cur.execute("SET LOCAL max_parallel_workers_per_gather = 0")
        t_sql = time.perf_counter()
        cur.execute(sql, params)
        rows = cur.fetchall()
    if timings is not None:
        timings["sql_ms"] = round((time.perf_counter() - t_sql) * 1000, 1)

    return _hits_from_rows(rows)


def merge_child_hits(
    primary: list[SearchHitV2],
    extra: list[SearchHitV2],
    *,
    limit: int,
) -> list[SearchHitV2]:
    """Scala broad + anchor trafienia, bez duplikatów child_id."""
    seen: set[str] = set()
    merged: list[SearchHitV2] = []
    for hit in sorted(
        [*extra, *primary],
        key=lambda h: h.hybrid_score,
        reverse=True,
    ):
        if hit.child_id in seen:
            continue
        seen.add(hit.child_id)
        merged.append(hit)
        if len(merged) >= limit:
            break
    return merged


async def search_hybrid_v2(
    conn: Connection,
    query: str,
    top_k: int,
    *,
    candidate_limit: int | None = None,
    anchor_terms: list[str] | None = None,
    lexical_query: str | None = None,
    metadata_filters: MetadataFilters | None = None,
    title_filter: bool = False,
    timings: dict[str, float] | None = None,
    fts_backend: FtsBackend = "gin",
) -> list[SearchHitV2]:
    t_embed = time.perf_counter()
    query_embedding = await embed_text(query)
    if timings is not None:
        timings["embed_ms"] = round((time.perf_counter() - t_embed) * 1000, 1)
    vec = to_vector_literal(query_embedding)
    anchors = anchor_terms if anchor_terms is not None else anchor_terms_from_text(query)
    if lexical_query and lexical_query.strip():
        topical_query = lexical_query.strip()
    else:
        topical_query = _sanitize_tsquery(query, exclude={a.lower() for a in anchors})
    limit = candidate_limit or max(top_k * HYBRID_CANDIDATE_MULTIPLIER, top_k)
    meta_sql, meta_params = (
        metadata_filters.sql_and("p") if metadata_filters else ("", [])
    )

    if title_filter and anchors:
        return await _search_anchor_pass(
            conn,
            query,
            anchors,
            limit=limit,
            metadata_filters=metadata_filters,
            fts_backend=fts_backend,
            timings=timings,
        )

    if title_filter:
        anchor_sql, anchor_params = _anchor_match_clause(
            anchors, fts_backend=fts_backend, include_parent=True
        )
        boost_cte, boost_sql, boost_cte_params, scored_boost_params = (
            "",
            "0.0::float8",
            (),
            (),
        )
    else:
        anchor_sql, anchor_params = "", []
        boost_cte, boost_sql, boost_cte_params, scored_boost_params = (
            _anchor_boost_broad(
                anchors,
                fts_backend=fts_backend,
                meta_sql=meta_sql,
                meta_params=meta_params,
            )
        )

    filter_sql = anchor_sql + meta_sql
    filter_params = anchor_params + meta_params
    parent_join = (
        "INNER JOIN chunks pa ON pa.id = ch.parent_id AND pa.chunk_role = 'parent'"
        if anchor_sql
        else ""
    )

    use_bm25 = fts_backend == "bm25"
    fts_text = topical_query or query.strip()[:500]
    vector_k, fts_k = hybrid_prefetch_limits(limit, fts=bool(fts_text))
    vector_papers_join = _papers_join_if(meta_sql)

    if fts_text and use_bm25:
        rrf_k = HYBRID_RRF_K
        bm25_query = _bm25_match_query(fts_text, anchors, broad=True)
        bm25_papers_join = _papers_join_if(meta_sql)
        sql = f"""
        WITH vector_hits AS (
            SELECT id, ROW_NUMBER() OVER () AS vec_rank
            FROM (
                SELECT ch.id
                FROM chunks ch
                {vector_papers_join}
                {parent_join}
                WHERE ch.chunk_role = 'child'
                  AND ch.embedding IS NOT NULL
                  AND ch.parent_id IS NOT NULL
                  {filter_sql}
                ORDER BY ch.embedding <=> %s::vector
                LIMIT %s
            ) v
        ),
        fts_hits AS (
            SELECT id, ROW_NUMBER() OVER () AS fts_rank
            FROM (
                SELECT ch.id
                FROM chunks ch
                {bm25_papers_join}
                WHERE ch.chunk_role = 'child'
                  AND ch.id @@@ paradedb.match('search_text', %s)
                  {meta_sql}
                ORDER BY paradedb.score(ch.id) DESC
                LIMIT %s
            ) f
        ),
        {boost_cte}
        rrf_parts AS (
            SELECT id, 1.0 / ({rrf_k} + vec_rank) AS score FROM vector_hits
            UNION ALL
            SELECT id, 1.0 / ({rrf_k} + fts_rank) AS score FROM fts_hits
        ),
        candidate_rrf AS (
            SELECT id, SUM(score) AS rrf_score
            FROM rrf_parts
            GROUP BY id
        ),
        scored AS (
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
                (ch.embedding <=> %s::vector) AS vector_distance,
                c.rrf_score AS text_score,
                ({boost_sql}) AS anchor_boost,
                c.rrf_score
            FROM candidate_rrf c
            INNER JOIN chunks ch ON ch.id = c.id
                AND ch.chunk_role = 'child'
                AND ch.embedding IS NOT NULL
                AND ch.parent_id IS NOT NULL
            INNER JOIN chunks pa
                ON pa.id = ch.parent_id AND pa.chunk_role = 'parent'
            INNER JOIN papers p ON p.id = ch.paper_id
        ),
        ranked AS (
            SELECT *,
                (rrf_score + anchor_boost) AS hybrid_score
            FROM scored
        )
        SELECT *
        FROM ranked
        ORDER BY hybrid_score DESC
        LIMIT %s
        """
        params = (
            *filter_params,
            vec,
            vector_k,
            bm25_query,
            *meta_params,
            fts_k,
            *boost_cte_params,
            vec,
            *scored_boost_params,
            limit,
        )
    elif fts_text:
        rrf_k = HYBRID_RRF_K
        papers_join = vector_papers_join or "INNER JOIN papers p ON p.id = ch.paper_id"
        sql = f"""
        WITH vector_hits AS (
            SELECT id, ROW_NUMBER() OVER () AS vec_rank
            FROM (
                SELECT ch.id
                FROM chunks ch
                {papers_join}
                {parent_join}
                WHERE ch.chunk_role = 'child'
                  AND ch.embedding IS NOT NULL
                  AND ch.parent_id IS NOT NULL
                  {filter_sql}
                ORDER BY ch.embedding <=> %s::vector
                LIMIT %s
            ) v
        ),
        fts_hits AS (
            SELECT id, ROW_NUMBER() OVER () AS fts_rank
            FROM (
                SELECT ch.id
                FROM chunks ch
                {papers_join}
                {parent_join}
                WHERE ch.chunk_role = 'child'
                  AND ch.embedding IS NOT NULL
                  AND ch.parent_id IS NOT NULL
                  AND plainto_tsquery('english', %s) @@ ch.text_search
                  {filter_sql}
                ORDER BY ts_rank(
                    ch.text_search,
                    plainto_tsquery('english', %s)
                ) DESC
                LIMIT %s
            ) f
        ),
        {boost_cte}
        rrf_parts AS (
            SELECT id, 1.0 / ({rrf_k} + vec_rank) AS score FROM vector_hits
            UNION ALL
            SELECT id, 1.0 / ({rrf_k} + fts_rank) AS score FROM fts_hits
        ),
        candidate_rrf AS (
            SELECT id, SUM(score) AS rrf_score
            FROM rrf_parts
            GROUP BY id
        ),
        scored AS (
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
                (ch.embedding <=> %s::vector) AS vector_distance,
                c.rrf_score AS text_score,
                ({boost_sql}) AS anchor_boost,
                c.rrf_score
            FROM candidate_rrf c
            INNER JOIN chunks ch ON ch.id = c.id
            INNER JOIN chunks pa
                ON pa.id = ch.parent_id AND pa.chunk_role = 'parent'
            INNER JOIN papers p ON p.id = ch.paper_id
        ),
        ranked AS (
            SELECT *,
                (rrf_score + anchor_boost) AS hybrid_score
            FROM scored
        )
        SELECT *
        FROM ranked
        ORDER BY hybrid_score DESC
        LIMIT %s
        """
        params = (
            *filter_params,
            vec,
            vector_k,
            topical_query,
            *filter_params,
            topical_query,
            fts_k,
            *boost_cte_params,
            vec,
            *scored_boost_params,
            limit,
        )
    else:
        fts_cte = ""
        fts_params = ()
        candidate_union = """
            candidate_ids AS (
                SELECT id FROM vector_hits
            ),"""
        hybrid_expr = "((1.0 - LEAST(vector_distance, 1.0)) + anchor_boost)"
        text_score_expr = "0.0::float8 AS text_score,"
        text_score_params = ()
        hybrid_params = ()
        sql = f"""
        WITH vector_hits AS (
            SELECT ch.id
            FROM chunks ch
            {papers_join}
            {parent_join}
            WHERE ch.chunk_role = 'child'
              AND ch.embedding IS NOT NULL
              AND ch.parent_id IS NOT NULL
              {filter_sql}
            ORDER BY ch.embedding <=> %s::vector
            LIMIT %s
        ),
        {candidate_union}
        scored AS (
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
                (ch.embedding <=> %s::vector) AS vector_distance,
                {text_score_expr}
                ({boost_sql}) AS anchor_boost
            FROM candidate_ids cid
            INNER JOIN chunks ch ON ch.id = cid.id
            INNER JOIN chunks pa
                ON pa.id = ch.parent_id AND pa.chunk_role = 'parent'
            INNER JOIN papers p ON p.id = ch.paper_id
        ),
        ranked AS (
            SELECT *,
                {hybrid_expr} AS hybrid_score
            FROM scored
        )
        SELECT *
        FROM ranked
        ORDER BY hybrid_score DESC
        LIMIT %s
        """
        params = (*filter_params, vec, vector_k, vec, *scored_boost_params, limit)

    if timings is not None:
        timings["fts_backend"] = fts_backend  # type: ignore[assignment]

    with conn.cursor() as cur:
        cur.execute("SET LOCAL max_parallel_workers_per_gather = 0")
        t_sql = time.perf_counter()
        cur.execute(sql, params)
        rows = cur.fetchall()
    if timings is not None:
        timings["sql_ms"] = round((time.perf_counter() - t_sql) * 1000, 1)

    return _hits_from_rows(rows)


def collapse_children_to_parents(children: list[SearchHitV2]) -> list[SearchHitV2]:
    """Krok 2 lejka: najlepsze Dziecko per Rodzic → lista kandydatów na rerank."""
    best_by_parent: dict[str, SearchHitV2] = {}
    for hit in sorted(children, key=lambda h: h.hybrid_score, reverse=True):
        if hit.parent_id not in best_by_parent:
            best_by_parent[hit.parent_id] = hit
    return sorted(best_by_parent.values(), key=lambda h: h.hybrid_score, reverse=True)
