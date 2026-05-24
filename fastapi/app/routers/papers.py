import re
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from app.db import get_db
from app.schemas import PaperResponse

router = APIRouter(prefix="/papers", tags=["papers"])

UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.I,
)


def _is_uuid(value: str) -> bool:
    if not UUID_RE.match(value):
        return False
    try:
        UUID(value)
        return True
    except ValueError:
        return False


@router.get("/{paper_id}", response_model=PaperResponse)
def get_paper(paper_id: str, conn: Connection = Depends(get_db)):
    if _is_uuid(paper_id):
        where = "p.id = %s::uuid"
        param = paper_id
    else:
        where = "p.arxiv_id = %s"
        param = paper_id

    sql = f"""
        SELECT
            p.id::text,
            p.arxiv_id,
            p.arxiv_url,
            p.pdf_url,
            p.title,
            p.summary,
            COALESCE(p.authors, ARRAY[]::text[]),
            COALESCE(p.categories, ARRAY[]::text[]),
            p.primary_category,
            p.published_at::text,
            p.storage_path,
            p.parsing_status,
            p.chunking_status,
            p.embedding_status,
            p.paper_token_count,
            (SELECT COUNT(*)::int FROM chunks c WHERE c.paper_id = p.id)
        FROM papers p
        WHERE {where}
    """

    with conn.cursor() as cur:
        cur.execute(sql, (param,))
        row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Paper not found")

    return PaperResponse(
        id=row[0],
        arxiv_id=row[1],
        arxiv_url=row[2],
        pdf_url=row[3],
        title=row[4],
        summary=row[5],
        authors=list(row[6] or []),
        categories=list(row[7] or []),
        primary_category=row[8],
        published_at=row[9],
        storage_path=row[10],
        parsing_status=row[11],
        chunking_status=row[12],
        embedding_status=row[13],
        paper_token_count=row[14],
        chunk_count=row[15],
    )
