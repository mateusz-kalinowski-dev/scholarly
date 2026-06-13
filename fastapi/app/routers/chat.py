from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from app.db import get_db
from app.schemas import ChatRequest, ChatResponse
from app.services.embeddings import EmbeddingError
from app.services.query_rewrite import rewrite_query_for_retrieval
from app.services.rag import (
    LLMError,
    build_llm_only_messages,
    build_rag_messages,
    generate_chat,
    hits_to_sources,
)
from app.services.retrieval import search_chunks
from app.services.source_translate import translate_source_chunks

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    conn: Connection = Depends(get_db),
):
    rewrite = None
    search_query = body.question
    answer_language: str | None = None

    if body.query_strategy == "rewrite":
        rewrite = await rewrite_query_for_retrieval(body.question)
        answer_language = rewrite.user_language
        if body.rag:
            search_query = rewrite.retrieval_query

    hits = []
    if body.rag:
        try:
            hits = await search_chunks(
                conn, search_query, body.top_k, body.mode
            )
        except EmbeddingError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

        if not hits:
            raise HTTPException(
                status_code=404,
                detail="Brak zindeksowanych chunków. Uruchom processor na danych.",
            )
        system, user = build_rag_messages(
            body.question,
            hits,
            answer_language=answer_language,
        )
    else:
        system, user = build_llm_only_messages(
            body.question,
            answer_language=answer_language,
        )

    try:
        answer = await generate_chat(system, user)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    sources, papers = hits_to_sources(hits) if body.rag else ([], [])
    if body.rag and body.query_strategy == "rewrite" and rewrite:
        sources = await translate_source_chunks(sources, rewrite.user_language)

    return ChatResponse(
        question=body.question,
        answer=answer,
        rag_enabled=body.rag,
        query_strategy=body.query_strategy,
        retrieval_query=rewrite.retrieval_query if rewrite else None,
        user_language=rewrite.user_language if rewrite else None,
        sources=sources,
        papers=papers,
    )
