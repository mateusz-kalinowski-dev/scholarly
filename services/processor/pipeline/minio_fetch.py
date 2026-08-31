"""Pobieranie surowego tekstu z MinIO (storage_path z v1)."""
from __future__ import annotations

import io

from minio import Minio

from config import BUCKET_NAME, MINIO_ACCESS_KEY, MINIO_ENDPOINT, MINIO_SECRET_KEY

_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
)


def load_text_from_storage_path(storage_path: str) -> str:
    """
    storage_path format: papers/2026/05/2605.08376.txt
    lub papers/2026/05/2605.08376.txt z bucket prefix.
    """
    path = storage_path.strip()
    if path.startswith(f"{BUCKET_NAME}/"):
        path = path[len(BUCKET_NAME) + 1 :]
    bucket = BUCKET_NAME
    obj = path
    if "/" in path and not path.startswith("20"):
        parts = path.split("/", 1)
        if parts[0] == BUCKET_NAME:
            obj = parts[1]

    response = _client.get_object(bucket, obj)
    try:
        return response.read().decode("utf-8", errors="ignore")
    finally:
        response.close()
        response.release_conn()
