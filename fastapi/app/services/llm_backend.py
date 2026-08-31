"""Wybór backendu LLM (Ollama vs OpenAI) per request — contextvar."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Literal

LlmBackend = Literal["ollama", "openai"]

_llm_backend: ContextVar[LlmBackend] = ContextVar("llm_backend", default="ollama")


def get_llm_backend() -> LlmBackend:
    return _llm_backend.get()


@contextmanager
def use_llm_backend(backend: LlmBackend) -> Iterator[None]:
    token = _llm_backend.set(backend)
    try:
        yield
    finally:
        _llm_backend.reset(token)
