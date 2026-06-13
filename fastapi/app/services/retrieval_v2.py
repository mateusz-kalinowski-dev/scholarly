"""Hybrid retrieval v2: child vector + FTS → parent context."""
from __future__ import annotations

import re

from psycopg import Connection

from app.config import (
    ANCHOR_HYBRID_BOOST,
    HYBRID_CANDIDATE_MULTIPLIER,
    HYBRID_TEXT_WEIGHT,
    HYBRID_VECTOR_WEIGHT,
)
from app.schemas import SearchHitV2
from app.services.embeddings import embed_text_v2, to_vector_literal

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


def _anchor_title_filter_clause(anchor_terms: list[str]) -> tuple[str, list[str]]:
    if not anchor_terms:
        return "", []
    clauses: list[str] = []
    params: list[str] = []
    for term in anchor_terms:
        clauses.append("p.title ILIKE %s")
        params.append(f"%{term}%")
    return f"AND ({' OR '.join(clauses)})", params


def _anchor_title_boost_clause(anchor_terms: list[str]) -> tuple[str, list[str], float]:
    if not anchor_terms:
        return "0.0::float8", [], 0.0
    clauses: list[str] = []
    params: list[str] = []
    for term in anchor_terms:
        clauses.append("p.title ILIKE %s")
        params.append(f"%{term}%")
    return f"CASE WHEN ({' OR '.join(clauses)}) THEN %s ELSE 0.0 END", params, ANCHOR_HYBRID_BOOST


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
    title_filter: bool = False,
) -> list[SearchHitV2]:
    query_embedding = await embed_text_v2(query)
    vec = to_vector_literal(query_embedding)
    anchors = anchor_terms if anchor_terms is not None else anchor_terms_from_text(query)
    topical_query = _sanitize_tsquery(query, exclude={a.lower() for a in anchors})
    limit = candidate_limit or max(top_k * HYBRID_CANDIDATE_MULTIPLIER, top_k)

    if title_filter:
        anchor_sql, anchor_params = _anchor_title_filter_clause(anchors)
        boost_sql, boost_params, boost_weight = "0.0::float8", [], 0.0
    else:
        anchor_sql, anchor_params = "", []
        boost_sql, boost_params, boost_weight = _anchor_title_boost_clause(anchors)

    if topical_query:
        scored_boost_params: tuple = ()
        if boost_sql != "0.0::float8":
            scored_boost_params = (*boost_params, boost_weight)

        sql = f"""
            WITH scored AS (
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
                    COALESCE(
                        GREATEST(
                            ts_rank(ch.text_search, plainto_tsquery('english', %s)),
                            ts_rank(pa.text_search, plainto_tsquery('english', %s))
                        ),
                        0
                    ) AS text_score,
                    ({boost_sql}) AS anchor_boost
                FROM chunks ch
                INNER JOIN chunks pa
                    ON pa.id = ch.parent_id AND pa.chunk_role = 'parent'
                INNER JOIN papers p ON p.id = ch.paper_id
                WHERE ch.chunk_role = 'child'
                  AND ch.embedding IS NOT NULL
                  AND ch.parent_id IS NOT NULL
                  {anchor_sql}
            ),
            ranked AS (
                SELECT *,
                    (%s * (1.0 - LEAST(vector_distance, 1.0))
                     + %s * text_score
                     + anchor_boost) AS hybrid_score
                FROM scored
            )
            SELECT *
            FROM ranked
            ORDER BY hybrid_score DESC
            LIMIT %s
        """
        params = (
            vec,
            topical_query,
            topical_query,
            *scored_boost_params,
            *anchor_params,
            HYBRID_VECTOR_WEIGHT,
            HYBRID_TEXT_WEIGHT,
            limit,
        )
    else:
        scored_boost_params = ()
        if boost_sql != "0.0::float8":
            scored_boost_params = (*boost_params, boost_weight)

        sql = f"""
            WITH scored AS (
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
                    0.0::float8 AS text_score,
                    ({boost_sql}) AS anchor_boost
                FROM chunks ch
                INNER JOIN chunks pa
                    ON pa.id = ch.parent_id AND pa.chunk_role = 'parent'
                INNER JOIN papers p ON p.id = ch.paper_id
                WHERE ch.chunk_role = 'child'
                  AND ch.embedding IS NOT NULL
                  AND ch.parent_id IS NOT NULL
                  {anchor_sql}
            ),
            ranked AS (
                SELECT *,
                    ((1.0 - LEAST(vector_distance, 1.0)) + anchor_boost) AS hybrid_score
                FROM scored
            )
            SELECT *
            FROM ranked
            ORDER BY hybrid_score DESC
            LIMIT %s
        """
        params = (vec, *scored_boost_params, *anchor_params, limit)

    with conn.cursor() as cur:
        cur.execute("SET LOCAL max_parallel_workers_per_gather = 0")
        cur.execute(sql, params)
        rows = cur.fetchall()

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


def collapse_children_to_parents(children: list[SearchHitV2]) -> list[SearchHitV2]:
    """Krok 2 lejka: najlepsze Dziecko per Rodzic → lista kandydatów na rerank."""
    best_by_parent: dict[str, SearchHitV2] = {}
    for hit in sorted(children, key=lambda h: h.hybrid_score, reverse=True):
        if hit.parent_id not in best_by_parent:
            best_by_parent[hit.parent_id] = hit
    return sorted(best_by_parent.values(), key=lambda h: h.hybrid_score, reverse=True)
