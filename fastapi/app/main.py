import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import chat, papers, search

load_dotenv()

app = FastAPI(
    title="Scholarly RAG API",
    description="Wyszukiwanie semantyczne i RAG nad pracami arXiv",
    version="0.2.0",
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


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "postgres_configured": bool(os.getenv("POSTGRES_URL")),
        "ollama_url": os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        "llm_model": os.getenv("LLM_MODEL", "gemma4:e2b"),
        "embed_model": os.getenv("EMBED_MODEL", "nomic-embed-text"),
    }
