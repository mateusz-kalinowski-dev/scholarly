"""Endpointy chat dla badań ablacyjnych (Baseline 0 → Eksperyment 2)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from psycopg import Connection

from app.db import get_db
from app.schemas import ChatRequestResearch, ChatResponseV2
from app.services.embeddings import EmbeddingError
from app.services.rag_v2 import LLMError
from app.services.research_pipeline import (
    VARIANTS,
    ResearchVariant,
    handle_research_chat,
)

router = APIRouter(prefix="/api/research", tags=["research"])


def _chat_endpoint(variant: ResearchVariant):
    async def _handler(
        body: ChatRequestResearch,
        conn: Connection = Depends(get_db),
    ) -> ChatResponseV2:
        try:
            return await handle_research_chat(body, conn, variant=variant)
        except EmbeddingError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        except LLMError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        except LookupError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    return _handler


router.add_api_route(
    "/baseline0/chat",
    _chat_endpoint("baseline0"),
    methods=["POST"],
    response_model=ChatResponseV2,
    summary="Baseline 0 — naiwny chunk, vector only",
)
router.add_api_route(
    "/baseline1/chat",
    _chat_endpoint("baseline1"),
    methods=["POST"],
    response_model=ChatResponseV2,
    summary="Baseline 1 — parent-child, vector + title/summary",
)
router.add_api_route(
    "/eksperyment1-gin/chat",
    _chat_endpoint("eksperyment1-gin"),
    methods=["POST"],
    response_model=ChatResponseV2,
    summary="Eksperyment 1 — hybrid GIN + rerank",
)
router.add_api_route(
    "/eksperyment1-bm25/chat",
    _chat_endpoint("eksperyment1-bm25"),
    methods=["POST"],
    response_model=ChatResponseV2,
    summary="Eksperyment 1 — hybrid BM25 + rerank",
)
router.add_api_route(
    "/eksperyment2/chat",
    _chat_endpoint("eksperyment2"),
    methods=["POST"],
    response_model=ChatResponseV2,
    summary="Eksperyment 2 — hybrid BM25 + rerank + Self-RAG",
)
router.add_api_route(
    "/eksperyment2-openai/chat",
    _chat_endpoint("eksperyment2-openai"),
    methods=["POST"],
    response_model=ChatResponseV2,
    summary="Eksperyment 2 + OpenAI — Self-RAG jak Exp2, LLM = OpenAI (szybki)",
)


@router.get("/variants")
async def list_variants():
    return {
        name: {
            "label": cfg.label,
            "endpoint": f"/api/research/{name}/chat",
            "hybrid": cfg.hybrid,
            "fts_backend": cfg.fts_backend,
            "rerank": cfg.rerank,
            "self_rag": cfg.self_rag,
            "llm_backend": cfg.llm_backend,
            "query_strategy": "rewrite",
        }
        for name, cfg in VARIANTS.items()
    }
