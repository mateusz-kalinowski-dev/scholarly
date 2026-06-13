from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from app.db import get_db
from app.schemas import SearchRequest, SearchResponse
from app.services.embeddings import EmbeddingError
from app.services.query_rewrite import rewrite_query_for_retrieval
from app.services.retrieval import search_chunks
from app.services.source_translate import translate_search_hits

router = APIRouter(prefix="/search", tags=["search"])


@router.post("", response_model=SearchResponse)
async def semantic_search(
    body: SearchRequest,
    conn: Connection = Depends(get_db),
):
    rewrite = None
    search_query = body.query

    if body.query_strategy == "rewrite":
        rewrite = await rewrite_query_for_retrieval(body.query)
        search_query = rewrite.retrieval_query

    try:
        hits = await search_chunks(conn, search_query, body.top_k, body.mode)
    except EmbeddingError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    if body.query_strategy == "rewrite" and rewrite:
        hits = await translate_search_hits(hits, rewrite.user_language)

    return SearchResponse(
        query=body.query,
        mode=body.mode,
        query_strategy=body.query_strategy,
        retrieval_query=rewrite.retrieval_query if rewrite else None,
        user_language=rewrite.user_language if rewrite else None,
        results=hits,
    )
