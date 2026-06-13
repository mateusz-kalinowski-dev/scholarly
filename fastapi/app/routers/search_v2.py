from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from app.db import get_db_v2
from app.schemas import SearchRequestV2, SearchResponseV2
from app.services.embeddings import EmbeddingError
from app.services.query_rewrite import rewrite_query_for_retrieval
from app.services.self_rag_v2 import retrieve_with_self_rag_v2

router = APIRouter(prefix="/api/v2/search", tags=["search-v2"])


@router.post("", response_model=SearchResponseV2)
async def search_v2(
    body: SearchRequestV2,
    conn: Connection = Depends(get_db_v2),
):
    rewrite = None
    search_query = body.query

    if body.query_strategy == "rewrite":
        rewrite = await rewrite_query_for_retrieval(body.query)
        search_query = rewrite.retrieval_query

    try:
        pipeline = await retrieve_with_self_rag_v2(
            conn,
            body.query,
            search_query,
            body.top_k,
            self_rag=False,
            for_chat=False,
        )
    except EmbeddingError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    return SearchResponseV2(
        query=body.query,
        query_strategy=body.query_strategy,
        retrieval_query=rewrite.retrieval_query if rewrite else None,
        user_language=rewrite.user_language if rewrite else None,
        retrieval=pipeline.meta,
        results=pipeline.hits,
    )
