from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from app.config import SELF_RAG_ENABLED, SELF_RAG_POST_GEN_ENABLED, RERANK_MIN_SCORE
from app.db import get_db_v2
from app.schemas import ChatRequestV2, ChatResponseV2
from app.services.embeddings import EmbeddingError
from app.services.query_rewrite import rewrite_query_for_retrieval
from app.services.rag import IDK_ANSWER
from app.services.rag_v2 import (
    LLMError,
    build_llm_only_messages_v2,
    build_rag_messages_v2,
    generate_chat,
    hits_to_sources_v2,
)
from app.services.self_rag_v2 import retrieve_with_self_rag_v2, verify_answer_grounded_v2

router = APIRouter(prefix="/api/v2/chat", tags=["chat-v2"])


@router.post("", response_model=ChatResponseV2)
async def chat_v2(
    body: ChatRequestV2,
    conn: Connection = Depends(get_db_v2),
):
    rewrite = None
    search_query = body.question
    answer_language: str | None = None
    retrieval_meta = None
    hits = []

    if body.query_strategy == "rewrite":
        rewrite = await rewrite_query_for_retrieval(body.question)
        answer_language = rewrite.user_language
        if body.rag:
            search_query = rewrite.retrieval_query

    if body.rag:
        try:
            pipeline = await retrieve_with_self_rag_v2(
                conn,
                body.question,
                search_query,
                body.top_k,
                self_rag=SELF_RAG_ENABLED,
            )
        except EmbeddingError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

        hits = pipeline.hits
        retrieval_meta = pipeline.meta

        if not hits:
            if retrieval_meta and not retrieval_meta.accepted:
                answer = IDK_ANSWER
            else:
                raise HTTPException(
                    status_code=404,
                    detail="Brak zindeksowanych chunków v2. Uruchom rechunk_v2.",
                )
            sources, papers = [], []
            return ChatResponseV2(
                question=body.question,
                answer=answer,
                rag_enabled=body.rag,
                query_strategy=body.query_strategy,
                retrieval_query=rewrite.retrieval_query if rewrite else None,
                user_language=rewrite.user_language if rewrite else None,
                retrieval=retrieval_meta,
                sources=sources,
                papers=papers,
            )

        system, user = build_rag_messages_v2(
            body.question,
            hits,
            answer_language=answer_language,
        )
    else:
        system, user = build_llm_only_messages_v2(
            body.question,
            answer_language=answer_language,
        )

    try:
        answer = await generate_chat(system, user)
    except LLMError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    answer_verified: bool | None = None
    if body.rag and hits and SELF_RAG_POST_GEN_ENABLED:
        candidate = answer
        answer_verified = await verify_answer_grounded_v2(
            body.question, candidate, hits
        )
        if not answer_verified and candidate.strip().lower() != IDK_ANSWER.lower():
            retry_system = system + (
                "\n\nCritical: Use ONLY facts explicitly present in the excerpts. "
                "If unsupported, reply exactly: I do not know."
            )
            try:
                candidate = await generate_chat(retry_system, user)
            except LLMError:
                pass
            answer_verified = await verify_answer_grounded_v2(
                body.question, candidate, hits
            )

        high_trust = (
            retrieval_meta is not None
            and (retrieval_meta.rerank_top_score or 0)
            >= max(RERANK_MIN_SCORE + 0.35, 0.65)
        )
        if not answer_verified:
            if high_trust and candidate.strip().lower() != IDK_ANSWER.lower():
                answer_verified = True
            elif candidate.strip().lower() != IDK_ANSWER.lower():
                candidate = IDK_ANSWER

        answer = candidate
        if retrieval_meta is not None:
            retrieval_meta = retrieval_meta.model_copy(
                update={"answer_verified": answer_verified}
            )

    sources, papers = hits_to_sources_v2(hits) if body.rag else ([], [])

    return ChatResponseV2(
        question=body.question,
        answer=answer,
        rag_enabled=body.rag,
        query_strategy=body.query_strategy,
        retrieval_query=rewrite.retrieval_query if rewrite else None,
        user_language=rewrite.user_language if rewrite else None,
        retrieval=retrieval_meta,
        sources=sources,
        papers=papers,
    )
