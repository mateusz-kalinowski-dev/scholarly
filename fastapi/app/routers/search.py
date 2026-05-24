from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from app.db import get_db
from app.schemas import SearchRequest, SearchResponse
from app.services.embeddings import EmbeddingError
from app.services.retrieval import search_chunks

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def semantic_search(
    body: SearchRequest,
    conn: Connection = Depends(get_db),
):
    try:
        hits = await search_chunks(conn, body.query, body.top_k, body.mode)
    except EmbeddingError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return SearchResponse(query=body.query, mode=body.mode, results=hits)
