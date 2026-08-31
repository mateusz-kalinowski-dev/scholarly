import os

from config import POSTGRES_URL  # noqa: F401 — wspólna baza z processor/config.py

B0_CHUNK_SIZE = int(os.getenv("B0_CHUNK_SIZE", "1000"))
B0_CHUNK_OVERLAP = int(os.getenv("B0_CHUNK_OVERLAP", "200"))
B0_PAPER_WORKERS = int(os.getenv("B0_PAPER_WORKERS", "4"))
B0_EMBED_WORKERS = int(os.getenv("B0_EMBED_WORKERS", "2"))
B0_EMBED_BATCH_SIZE = int(os.getenv("B0_EMBED_BATCH_SIZE", "32"))
B0_EMBED_ACCUMULATE = int(os.getenv("B0_EMBED_ACCUMULATE", "128"))
B0_EMBED_MAX_INFLIGHT = int(os.getenv("B0_EMBED_MAX_INFLIGHT", "8"))
B0_EMBED_SERIAL = os.getenv("B0_EMBED_SERIAL", "false").lower() in ("1", "true", "yes")
B0_DB_INSERT_BATCH = int(os.getenv("B0_DB_INSERT_BATCH", "100"))
