import httpx

from app.config import EMBED_MAX_CHARS, EMBED_MODEL, OLLAMA_BASE_URL


class EmbeddingError(Exception):
    pass


def to_vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(v) for v in values) + "]"


async def embed_text(text: str) -> list[float]:
    if not text.strip():
        raise EmbeddingError("Pusty tekst do embeddingu")

    trimmed = text[:EMBED_MAX_CHARS]
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{OLLAMA_BASE_URL}/api/embed",
            json={"model": EMBED_MODEL, "input": trimmed},
        )

    if response.status_code != 200:
        raise EmbeddingError(
            f"Ollama embed HTTP {response.status_code}: {response.text[:200]}"
        )

    data = response.json()
    embeddings = data.get("embeddings")
    if embeddings and len(embeddings) == 1:
        return embeddings[0]
    embedding = data.get("embedding")
    if embedding:
        return embedding
    raise EmbeddingError("Brak wektora w odpowiedzi Ollama")
