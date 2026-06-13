import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    HYBRID_CHILD_RECALL_MAX,
    HYBRID_CHILD_RECALL_MIN,
    LLM_CONTEXT_TOP_K,
    RERANK_ENABLED,
    RERANK_MIN_SCORE,
    RERANK_MODEL,
    RERANK_TOP_N,
    SELF_RAG_ENABLED,
    SELF_RAG_POST_GEN_ENABLED,
)
from app.routers import chat, chat_v2, papers, search, search_v2

load_dotenv()

app = FastAPI(
    title="Scholarly RAG API",
    description="Wyszukiwanie semantyczne i RAG nad pracami arXiv",
    version="0.3.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(search.router)
app.include_router(chat.router)
app.include_router(papers.router)
app.include_router(search_v2.router)
app.include_router(chat_v2.router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "v1": {
            "postgres": os.getenv("POSTGRES_URL", "").split("@")[-1],
            "embed_model": os.getenv("EMBED_MODEL", "nomic-embed-text"),
        },
        "v2": {
            "postgres": os.getenv("POSTGRES_V2_URL", "").split("@")[-1],
            "embed_model": os.getenv("EMBED_MODEL_V2", "bge-m3"),
            "hybrid": True,
            "child_recall": f"{HYBRID_CHILD_RECALL_MIN}-{HYBRID_CHILD_RECALL_MAX}",
            "rerank": RERANK_ENABLED,
            "rerank_model": RERANK_MODEL,
            "rerank_top_n": RERANK_TOP_N,
            "rerank_min_score": RERANK_MIN_SCORE,
            "llm_context_top_k": LLM_CONTEXT_TOP_K,
            "self_rag": SELF_RAG_ENABLED,
            "self_rag_post_gen": SELF_RAG_POST_GEN_ENABLED,
        },
        "ollama_url": os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        "llm_model": os.getenv("LLM_MODEL", "gemma4:e2b"),
    }
