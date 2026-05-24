"""Pobieranie źródeł arXiv i zapis do MinIO."""
from __future__ import annotations

import gzip
import io
import logging
import re
import tarfile

import requests
from minio import Minio

from config import BUCKET_NAME, MINIO_ACCESS_KEY, MINIO_ENDPOINT, MINIO_SECRET_KEY

logger = logging.getLogger(__name__)

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False,
)

if not minio_client.bucket_exists(BUCKET_NAME):
    minio_client.make_bucket(BUCKET_NAME)


def source_url_for(arxiv_id: str, source_url: str | None) -> str:
    if source_url:
        return source_url
    return f"https://arxiv.org/e-print/{arxiv_id}"


def pdf_url_for(arxiv_id: str, pdf_url: str | None) -> str:
    if pdf_url:
        return pdf_url
    return f"https://arxiv.org/pdf/{arxiv_id}"


def download_and_extract_tex(source_url: str, arxiv_id: str) -> tuple[str, str]:
    year = f"20{arxiv_id[0:2]}"
    month = arxiv_id[2:4]
    object_name = f"{year}/{month}/{arxiv_id}.txt"

    response = requests.get(source_url, timeout=120)
    response.raise_for_status()
    file_bytes = io.BytesIO(response.content)
    text_content = ""

    try:
        with tarfile.open(fileobj=file_bytes, mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith(".tex"):
                    f = tar.extractfile(member)
                    if f:
                        text_content += f.read().decode("utf-8", errors="ignore") + "\n"
    except tarfile.ReadError:
        file_bytes.seek(0)
        try:
            with gzip.GzipFile(fileobj=file_bytes) as gz:
                text_content = gz.read().decode("utf-8", errors="ignore")
        except OSError:
            text_content = response.text

    text_content = re.sub(r"(?m)^%.*$", "", text_content)
    return _upload_text(object_name, text_content)


def extract_text_from_pdf(pdf_url: str, arxiv_id: str) -> tuple[str, str]:
    import fitz

    year = f"20{arxiv_id[0:2]}"
    month = arxiv_id[2:4]
    object_name = f"{year}/{month}/{arxiv_id}.txt"

    response = requests.get(pdf_url, timeout=120)
    response.raise_for_status()
    doc = fitz.open(stream=response.content, filetype="pdf")
    parts = [page.get_text() for page in doc]
    doc.close()
    text_content = "\n".join(parts)
    return _upload_text(object_name, text_content)


def _upload_text(object_name: str, text_content: str) -> tuple[str, str]:
    text_bytes = text_content.encode("utf-8")
    minio_client.put_object(
        BUCKET_NAME,
        object_name,
        io.BytesIO(text_bytes),
        length=len(text_bytes),
        content_type="text/plain",
    )
    storage_path = f"{BUCKET_NAME}/{object_name}"
    return storage_path, text_content


def fetch_raw_text(arxiv_id: str, source_url: str | None, pdf_url: str | None) -> tuple[str, str]:
    """e-print → fallback PDF."""
    try:
        src = source_url_for(arxiv_id, source_url)
        storage_path, raw = download_and_extract_tex(src, arxiv_id)
        if raw.strip():
            return storage_path, raw
        logger.warning("[%s] Pusty e-print, próbuję PDF...", arxiv_id)
    except Exception as e:
        logger.warning("[%s] e-print nieudany: %s — PDF fallback", arxiv_id, e)

    pdf = pdf_url_for(arxiv_id, pdf_url)
    storage_path, raw = extract_text_from_pdf(pdf, arxiv_id)
    return storage_path, raw
