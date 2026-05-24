from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from app.db import get_db
from app.schemas import ChatRequest, ChatResponse
from app.services.embeddings import EmbeddingError
from app.services.rag import (
    LLMError,
    build_llm_only_prompt,
    build_rag_prompt,
    generate_answer,
    hits_to_sources,
)
from app.services.retrieval import search_chunks

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    conn: Connection = Depends(get_db),
):
    hits = []
    if body.rag:
        try:
            hits = await search_chunks(
                conn, body.question, body.top_k, body.mode
            )
        except EmbeddingError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

        if not hits:
            raise HTTPException(
                status_code=404,
                detail="Brak zindeksowanych chunków. Uruchom processor na danych.",
            )
        prompt = build_rag_prompt(body.question, hits)
    else:
        prompt = build_llm_only_prompt(body.question)

    try:
        answer = await generate_answer(prompt)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    sources, papers = hits_to_sources(hits) if body.rag else ([], [])

    return ChatResponse(
        question=body.question,
        answer=answer,
        rag_enabled=body.rag,
        sources=sources,
        papers=papers,
    )
