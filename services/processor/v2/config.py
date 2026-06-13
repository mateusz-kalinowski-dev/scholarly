import os

POSTGRES_V2_URL = os.getenv(
    "POSTGRES_V2_URL",
    "postgresql://admin:admin@localhost:5445/papers_db_v2",
)
OLLAMA_URL = os.getenv("LLM_BASE_URL", os.getenv("OLLAMA_URL", "http://localhost:11434"))
EMBED_MODEL = os.getenv("EMBED_MODEL_V2", "bge-m3")
EMBED_DIM = 1024
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "16"))
EMBED_MAX_CHARS = int(os.getenv("EMBED_MAX_CHARS", "8000"))
EMBED_REQUEST_TIMEOUT = int(os.getenv("EMBED_REQUEST_TIMEOUT", "300"))

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
BUCKET_NAME = "papers"

PARENT_MAX_TOKENS = int(os.getenv("V2_PARENT_MAX_TOKENS", "1800"))
CHILD_CHUNK_TOKENS = int(os.getenv("V2_CHILD_CHUNK_TOKENS", "400"))
CHILD_OVERLAP_TOKENS = int(os.getenv("V2_CHILD_OVERLAP_TOKENS", "80"))
MIN_CHILD_TOKENS = int(os.getenv("V2_MIN_CHILD_TOKENS", "30"))
