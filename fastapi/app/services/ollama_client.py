"""Ollama — awaryjne odświeżenie stanu GPU (tylko przy błędzie embed NaN)."""
from __future__ import annotations

import asyncio
import logging

import httpx

from app.config import EMBED_MODEL_V2, OLLAMA_BASE_URL

logger = logging.getLogger(__name__)


async def recover_embed_after_nan() -> None:
    """Rzadki fallback: przeładuj embedder gdy bge-m3 zwróci NaN."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(
                f"{OLLAMA_BASE_URL}/api/generate",
                json={"model": EMBED_MODEL_V2, "keep_alive": 0},
            )
    except Exception:
        logger.debug("recover_embed_after_nan failed", exc_info=True)
    await asyncio.sleep(0.2)
