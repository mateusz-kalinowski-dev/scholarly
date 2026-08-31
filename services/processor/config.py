import os

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
POSTGRES_URL = os.getenv(
    "POSTGRES_URL", "postgresql://admin:admin@postgres:5432/papers_db_v2"
)

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
BUCKET_NAME = "papers"

OLLAMA_URL = os.getenv("LLM_BASE_URL", "http://ollama:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "bge-m3")
EMBED_DIM = 1024
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "16"))
EMBED_MAX_CHARS = int(os.getenv("EMBED_MAX_CHARS", "8000"))
EMBED_REQUEST_TIMEOUT = int(os.getenv("EMBED_REQUEST_TIMEOUT", "300"))
RABBITMQ_PREFETCH = int(os.getenv("RABBITMQ_PREFETCH", "1"))

SEARCH_INDEX_EVERY_N_PAPERS = int(os.getenv("SEARCH_INDEX_EVERY_N_PAPERS", "25"))
SEARCH_INDEX_COUNTER_KEY = "processor:papers_since_search_index"

PARENT_MAX_TOKENS = int(os.getenv("PARENT_MAX_TOKENS", "1800"))
CHILD_CHUNK_TOKENS = int(os.getenv("CHILD_CHUNK_TOKENS", "400"))
CHILD_OVERLAP_TOKENS = int(os.getenv("CHILD_OVERLAP_TOKENS", "80"))
MIN_CHILD_TOKENS = int(os.getenv("MIN_CHILD_TOKENS", "30"))
