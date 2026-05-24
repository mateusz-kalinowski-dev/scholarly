from psycopg import Connection

from app.config import HIERARCHICAL_PAPER_LIMIT
from app.schemas import SearchHit
from app.services.embeddings import embed_text, to_vector_literal


def _row_to_hit(row, score_idx: int = -1) -> SearchHit:
    score = float(row[score_idx]) if row[score_idx] is not None else 0.0
    return SearchHit(
        chunk_id=str(row[0]),
        paper_id=str(row[1]),
        arxiv_id=row[2],
        title=row[3],
        arxiv_url=row[4],
        section_name=row[5],
        subsection_name=row[6],
        chunk_index=row[7],
        content=row[8],
        score=score,
    )


async def search_chunks(
    conn: Connection,
    query: str,
    top_k: int,
    mode: str,
) -> list[SearchHit]:
    query_embedding = await embed_text(query)
    vec = to_vector_literal(query_embedding)

    if mode == "hierarchical":
        return _search_hierarchical(conn, vec, top_k)
    return _search_chunks_only(conn, vec, top_k)


def _search_chunks_only(conn: Connection, vec: str, top_k: int) -> list[SearchHit]:
    sql = """
        SELECT
            c.id::text,
            p.id::text,
            p.arxiv_id,
            p.title,
            p.arxiv_url,
            c.section_name,
            c.subsection_name,
            c.chunk_index,
            c.content,
            1 - (c.embedding <=> %s::vector) AS score
        FROM chunks c
        JOIN papers p ON p.id = c.paper_id
        WHERE c.embedding IS NOT NULL
        ORDER BY c.embedding <=> %s::vector
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, (vec, vec, top_k))
        rows = cur.fetchall()
    return [_row_to_hit(r) for r in rows]


def _search_hierarchical(conn: Connection, vec: str, top_k: int) -> list[SearchHit]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.id::text
            FROM papers p
            JOIN paper_embeddings pe ON pe.paper_id = p.id
            WHERE pe.summary_embedding IS NOT NULL
            ORDER BY pe.summary_embedding <=> %s::vector
            LIMIT %s
            """,
            (vec, HIERARCHICAL_PAPER_LIMIT),
        )
        paper_ids = [r[0] for r in cur.fetchall()]

        if not paper_ids:
            return _search_chunks_only(conn, vec, top_k)

        cur.execute(
            """
            SELECT
                c.id::text,
                p.id::text,
                p.arxiv_id,
                p.title,
                p.arxiv_url,
                c.section_name,
                c.subsection_name,
                c.chunk_index,
                c.content,
                1 - (c.embedding <=> %s::vector) AS score
            FROM chunks c
            JOIN papers p ON p.id = c.paper_id
            WHERE c.embedding IS NOT NULL
              AND p.id = ANY(%s)
            ORDER BY c.embedding <=> %s::vector
            LIMIT %s
            """,
            (vec, paper_ids, vec, top_k),
        )
        rows = cur.fetchall()

    if not rows:
        return _search_chunks_only(conn, vec, top_k)
    return [_row_to_hit(r) for r in rows]
