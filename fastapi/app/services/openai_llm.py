"""OpenAI Chat Completions — szybki LLM dla wariantu research (vs lokalna Ollama)."""
from __future__ import annotations

import httpx

from app.config import OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_CHAT_MODEL
from app.services.rag import LLMError


def _headers() -> dict[str, str]:
    if not OPENAI_API_KEY:
        raise LLMError(
            "Brak OPENAI_API_KEY — ustaw w fastapi/.env (wariant eksperyment2-openai)."
        )
    return {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }


async def openai_chat(system: str, user: str) -> str:
    payload = {
        "model": OPENAI_CHAT_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(
            f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions",
            headers=_headers(),
            json=payload,
        )
    if response.status_code != 200:
        raise LLMError(
            f"OpenAI chat HTTP {response.status_code}: {response.text[:300]}"
        )
    data = response.json()
    try:
        answer = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"OpenAI chat: nieoczekiwana odpowiedź: {data!r}") from e
    if not answer:
        raise LLMError("Pusta odpowiedź z OpenAI chat")
    return answer


async def openai_completion(prompt: str) -> str:
    """Jednostrzałowy prompt (rewrite / Self-RAG grade) przez Chat Completions."""
    payload = {
        "model": OPENAI_CHAT_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(
            f"{OPENAI_BASE_URL.rstrip('/')}/chat/completions",
            headers=_headers(),
            json=payload,
        )
    if response.status_code != 200:
        raise LLMError(
            f"OpenAI completion HTTP {response.status_code}: {response.text[:300]}"
        )
    data = response.json()
    try:
        answer = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"OpenAI completion: nieoczekiwana odpowiedź: {data!r}") from e
    if not answer:
        raise LLMError("Pusta odpowiedź z OpenAI completion")
    return answer
