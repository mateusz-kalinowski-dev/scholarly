import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    EMBED_MODEL,
    HYBRID_CHILD_RECALL_MAX,
    HYBRID_CHILD_RECALL_MIN,
    LLM_CONTEXT_TOP_K,
    POSTGRES_URL,
    RERANK_ENABLED,
    RERANK_MIN_SCORE,
    RERANK_MODEL,
    RERANK_TOP_N,
    SELF_RAG_ENABLED,
    SELF_RAG_POST_GEN_ENABLED,
)
from app.routers import research

load_dotenv()

app = FastAPI(
    title="Scholarly RAG API",
    description="RAG nad pracami arXiv — endpointy research (ablacje B0→Exp2)",
    version="0.4.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(research.router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "postgres": POSTGRES_URL.split("@")[-1],
        "embed_model": EMBED_MODEL,
        "hybrid": True,
        "fts_default": "gin",
        "research_endpoints": {
            "baseline0": "/api/research/baseline0/chat",
            "baseline1": "/api/research/baseline1/chat",
            "eksperyment1_gin": "/api/research/eksperyment1-gin/chat",
            "eksperyment1_bm25": "/api/research/eksperyment1-bm25/chat",
            "eksperyment2": "/api/research/eksperyment2/chat",
            "variants": "/api/research/variants",
        },
        "child_recall": f"{HYBRID_CHILD_RECALL_MIN}-{HYBRID_CHILD_RECALL_MAX}",
        "rerank": RERANK_ENABLED,
        "rerank_model": RERANK_MODEL,
        "rerank_top_n": RERANK_TOP_N,
        "rerank_min_score": RERANK_MIN_SCORE,
        "llm_context_top_k": LLM_CONTEXT_TOP_K,
        "self_rag": SELF_RAG_ENABLED,
        "self_rag_post_gen": SELF_RAG_POST_GEN_ENABLED,
        "ollama_url": os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        "llm_model": os.getenv("LLM_MODEL", "gemma4:e2b"),
    }
