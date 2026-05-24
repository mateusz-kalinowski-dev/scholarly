import os

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
POSTGRES_URL = os.getenv(
    "POSTGRES_URL", "postgresql://admin:admin@postgres:5432/papers_db"
)
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "minio:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
OLLAMA_URL = os.getenv("LLM_BASE_URL", "http://ollama:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
EMBED_BATCH_SIZE = int(os.getenv("EMBED_BATCH_SIZE", "32"))
EMBED_MAX_CHARS = int(os.getenv("EMBED_MAX_CHARS", "8000"))
EMBED_REQUEST_TIMEOUT = int(os.getenv("EMBED_REQUEST_TIMEOUT", "300"))
RABBITMQ_PREFETCH = int(os.getenv("RABBITMQ_PREFETCH", "1"))

# IVFFlat: CREATE/REINDEX co N ukończonych prac (nie po każdej)
IVFFLAT_INDEX_EVERY_N_PAPERS = int(os.getenv("IVFFLAT_INDEX_EVERY_N_PAPERS", "25"))
IVFFLAT_MIN_CHUNKS = int(os.getenv("IVFFLAT_MIN_CHUNKS", "100"))
IVFFLAT_COUNTER_KEY = "processor:papers_since_ivfflat"

BUCKET_NAME = "papers"

# Progi strategii chunkingu (szacowane tokeny)
SHORT_PAPER_MAX_TOKENS = 2000
LONG_PAPER_MIN_TOKENS = 12000
STANDARD_CHUNK_TOKENS = 800
STANDARD_OVERLAP_TOKENS = 150
SHORT_MAX_CHUNKS = 3
