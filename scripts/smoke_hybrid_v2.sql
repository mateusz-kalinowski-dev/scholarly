-- Smoke test hybrid child→parent (uruchom po --build-indexes)
-- docker exec -i postgres_v2 psql -U admin -d papers_db_v2 < scripts/smoke_hybrid_v2.sql

\set q 'underwater image enhancement PSNR EUVP'

WITH qvec AS (
    SELECT NULL::vector AS v  -- wstaw wektor z API lub pomiń wektor w teście FTS-only
),
scored AS (
    SELECT
        ch.id::text AS child_id,
        ch.parent_id::text,
        p.arxiv_id,
        p.title,
        ch.section_name,
        left(ch.content, 120) AS child_preview,
        left(pa.content, 200) AS parent_preview,
        (ch.embedding <=> (SELECT v FROM qvec)) AS vector_distance,
        ts_rank(ch.text_search, plainto_tsquery('english', :'q')) AS text_score
    FROM chunks ch
    JOIN chunks pa ON pa.id = ch.parent_id AND pa.chunk_role = 'parent'
    JOIN papers p ON p.id = ch.paper_id
    WHERE ch.chunk_role = 'child'
      AND ch.embedding IS NOT NULL
      AND plainto_tsquery('english', :'q') @@ ch.text_search
    ORDER BY text_score DESC
    LIMIT 5
)
SELECT * FROM scored;
