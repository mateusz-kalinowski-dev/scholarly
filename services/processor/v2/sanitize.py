"""Czyszczenie tekstu pod Postgres i embeddingi."""
from __future__ import annotations

import re

_PLACEHOLDER_RE = re.compile(r"⟦SACRED:(\d+)⟧")


def strip_nul(text: str) -> str:
    return text.replace("\x00", "") if text else ""


def sanitize_db_text(text: str) -> str:
    """Usuwa bajty NUL i znaki kontrolne (zostawia \\n, \\t)."""
    if not text:
        return ""
    text = strip_nul(text)
    text = "".join(
        c for c in text if c in "\n\t" or ord(c) >= 32
    )
    return text.strip()


def sanitize_embed_text(text: str, *, max_chars: int = 8000) -> str:
    """Tekst bezpieczny dla Ollama/bge-m3 (bez NUL, bez pustych wejść)."""
    text = sanitize_db_text(text)
    text = re.sub(r"\s+", " ", text).strip()
    if max_chars:
        text = text[:max_chars]
    return text or " "


def strip_legacy_sacred_placeholders(text: str) -> str:
    """Usuwa osierocone ⟦SACRED:n⟧ z poprzedniego pipeline (MinIO / v1)."""
    if not text:
        return ""
    return _PLACEHOLDER_RE.sub(" ", text)


def sacred_placeholder(idx: int) -> str:
    return f"⟦SACRED:{idx}⟧"


def replace_sacred_placeholder(text: str, idx: int, replacement: str) -> str:
    return text.replace(sacred_placeholder(idx), replacement, 1)
