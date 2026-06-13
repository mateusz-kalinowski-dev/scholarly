import httpx

from app.config import (
    EMBED_DIM_V2,
    EMBED_MAX_CHARS,
    EMBED_MODEL,
    EMBED_MODEL_V2,
    OLLAMA_BASE_URL,
)


class EmbeddingError(Exception):
    pass


def to_vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(v) for v in values) + "]"


async def _embed_with_model(text: str, model: str, expected_dim: int | None) -> list[float]:
    if not text.strip():
        raise EmbeddingError("Pusty tekst do embeddingu")

    trimmed = text[:EMBED_MAX_CHARS]
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/embed",
            json={"model": model, "input": trimmed},
        )

    if response.status_code != 200:
        raise EmbeddingError(
            f"Ollama embed HTTP {response.status_code}: {response.text[:200]}"
        )

    data = response.json()
    embeddings = data.get("embeddings")
    if embeddings and len(embeddings) == 1:
        vec = embeddings[0]
    else:
        vec = data.get("embedding")
    if not vec:
        raise EmbeddingError("Brak wektora w odpowiedzi Ollama")
    if expected_dim and len(vec) != expected_dim:
        raise EmbeddingError(
            f"Nieoczekiwany wymiar {len(vec)} (oczekiwano {expected_dim}, model={model})"
        )
    return vec


async def embed_text(text: str) -> list[float]:
    return await _embed_with_model(text, EMBED_MODEL, expected_dim=None)


async def embed_text_v2(text: str) -> list[float]:
    return await _embed_with_model(
        text, EMBED_MODEL_V2, expected_dim=EMBED_DIM_V2
    )
