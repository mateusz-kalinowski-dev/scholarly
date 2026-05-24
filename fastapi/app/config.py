import os

POSTGRES_URL = os.getenv(
    "POSTGRES_URL", "postgresql://admin:admin@postgres:5432/papers_db"
)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
LLM_MODEL = os.getenv("LLM_MODEL", "gemma4:e2b")

DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "5"))
HIERARCHICAL_PAPER_LIMIT = int(os.getenv("HIERARCHICAL_PAPER_LIMIT", "5"))
EMBED_MAX_CHARS = 8000
LLM_MAX_CONTEXT_CHARS = 12000
