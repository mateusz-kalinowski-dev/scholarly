import os

POSTGRES_URL = os.getenv(
    "POSTGRES_URL", "postgresql://admin:admin@postgres:5432/papers_db"
)
POSTGRES_V2_URL = os.getenv(
    "POSTGRES_V2_URL",
    "postgresql://admin:admin@postgres_v2:5432/papers_db_v2",
)
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
EMBED_MODEL_V2 = os.getenv("EMBED_MODEL_V2", "bge-m3")
EMBED_DIM_V2 = int(os.getenv("EMBED_DIM_V2", "1024"))
LLM_MODEL = os.getenv("LLM_MODEL", "gemma4:e2b")

DEFAULT_TOP_K = int(os.getenv("DEFAULT_TOP_K", "5"))
HIERARCHICAL_PAPER_LIMIT = int(os.getenv("HIERARCHICAL_PAPER_LIMIT", "5"))
EMBED_MAX_CHARS = int(os.getenv("EMBED_MAX_CHARS", "8000"))
LLM_MAX_CONTEXT_CHARS = int(os.getenv("LLM_MAX_CONTEXT_CHARS", "12000"))

HYBRID_VECTOR_WEIGHT = float(os.getenv("HYBRID_VECTOR_WEIGHT", "0.65"))
HYBRID_TEXT_WEIGHT = float(os.getenv("HYBRID_TEXT_WEIGHT", "0.35"))
HYBRID_CANDIDATE_MULTIPLIER = int(os.getenv("HYBRID_CANDIDATE_MULTIPLIER", "20"))
HYBRID_CHILD_RECALL_MIN = int(os.getenv("HYBRID_CHILD_RECALL_MIN", "100"))
HYBRID_CHILD_RECALL_MAX = int(os.getenv("HYBRID_CHILD_RECALL_MAX", "100"))
ANCHOR_CHILD_QUOTA = int(os.getenv("ANCHOR_CHILD_QUOTA", "25"))
ANCHOR_HYBRID_BOOST = float(os.getenv("ANCHOR_HYBRID_BOOST", "0.08"))

RERANK_ENABLED = os.getenv("RERANK_ENABLED", "true").lower() in ("1", "true", "yes")
RERANK_MODEL = os.getenv("RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
RERANK_TOP_N = int(os.getenv("RERANK_TOP_N", "50"))
RERANK_MIN_SCORE = float(os.getenv("RERANK_MIN_SCORE", "0.3"))
RERANK_MAX_CHARS = int(os.getenv("RERANK_MAX_CHARS", "2000"))

LLM_CONTEXT_TOP_K = int(os.getenv("LLM_CONTEXT_TOP_K", "8"))
SEARCH_RESULT_MAX = int(os.getenv("SEARCH_RESULT_MAX", "20"))

SELF_RAG_ENABLED = os.getenv("SELF_RAG_ENABLED", "true").lower() in ("1", "true", "yes")
SELF_RAG_MIN_CONFIDENCE = float(os.getenv("SELF_RAG_MIN_CONFIDENCE", "0.45"))
SELF_RAG_MAX_RETRIES = int(os.getenv("SELF_RAG_MAX_RETRIES", "1"))
SELF_RAG_GRADE_EXCERPTS = int(os.getenv("SELF_RAG_GRADE_EXCERPTS", "5"))
SELF_RAG_POST_GEN_ENABLED = os.getenv(
    "SELF_RAG_POST_GEN_ENABLED", "true"
).lower() in ("1", "true", "yes")


def child_recall_limit(top_k: int) -> int:
    """Krok 1 lejka: stałe ~100 Dzieci (recall po całym korpusie)."""
    scaled = top_k * HYBRID_CANDIDATE_MULTIPLIER
    return max(HYBRID_CHILD_RECALL_MIN, min(scaled, HYBRID_CHILD_RECALL_MAX))


def llm_context_limit(top_k: int) -> int:
    """Krok 4 lejka (chat): max Rodziców wysyłanych do LLM."""
    return max(1, min(top_k, LLM_CONTEXT_TOP_K))


def search_result_limit(top_k: int) -> int:
    """Search UI: ile rodziców zwrócić po reranku (bez limitu LLM)."""
    return max(1, min(top_k, SEARCH_RESULT_MAX))
