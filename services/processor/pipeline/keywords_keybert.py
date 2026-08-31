"""KeyBERT + regex — słowa kluczowe pod FTS/BM25 (search_text)."""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

from .keywords import extract_keywords

_MATH_SACRED = frozenset({"equation", "display_math", "inline_math"})
_MAX_KEYBERT_INPUT = 6000


def build_keybert_input(
    content: str,
    *,
    paper_title: str = "",
    section_name: str | None = None,
    subsection_name: str | None = None,
) -> str:
    parts = [p for p in (paper_title, section_name, subsection_name, content) if p]
    text = re.sub(r"\s+", " ", " — ".join(parts)).strip()
    return text[:_MAX_KEYBERT_INPUT]


def extract_keybert_phrases(
    kw_model,
    texts: list[str],
    *,
    max_keywords: int = 12,
    encode_batch_size: int = 128,
    ngram_range: tuple[int, int] = (2, 3),
    use_mmr: bool = True,
    diversity: float = 0.4,
    nr_candidates: int = 20,
) -> list[list[str]]:
    if not texts:
        return []
    cleaned = [re.sub(r"\s+", " ", t).strip() for t in texts]
    eligible = [i for i, t in enumerate(cleaned) if len(t) >= 40]
    out: list[list[str]] = [[] for _ in texts]

    if not eligible:
        return out

    try:
        batch_results = kw_model.extract_keywords(
            [cleaned[i] for i in eligible],
            keyphrase_ngram_range=ngram_range,
            stop_words="english",
            top_n=max_keywords,
            use_mmr=use_mmr,
            diversity=diversity,
            nr_candidates=nr_candidates,
        )
    except Exception:
        logger.exception("KeyBERT extract_keywords failed (batch=%d)", len(eligible))
        return out

    if eligible and not isinstance(batch_results[0], list):
        batch_results = [batch_results]

    for idx, pairs in zip(eligible, batch_results):
        if not pairs:
            continue
        phrases: list[str] = []
        for item in pairs:
            if isinstance(item, (list, tuple)) and item:
                phrase = str(item[0])
            elif isinstance(item, str):
                phrase = item
            else:
                continue
            if phrase.strip() and len(phrase.strip()) > 2:
                phrases.append(phrase.strip())
        out[idx] = phrases
    return out


def merge_chunk_keywords(
    content: str,
    *,
    paper_title: str,
    section_name: str | None,
    subsection_name: str | None = None,
    sacred_type: str | None,
    keybert: list[str],
    max_total: int = 28,
) -> tuple[list[str], list[str]]:
    """
    Zwraca (keywords regex, keywords_keybert unikalne względem regex).
    search_text = content + oba (trigger).
    """
    regex_kw = extract_keywords(
        content,
        paper_title=paper_title,
        section_name=section_name,
        subsection_name=subsection_name,
        sacred_type=sacred_type,
        max_keywords=18,
    )
    if sacred_type in _MATH_SACRED:
        return regex_kw[:max_total], []

    regex_lower = {k.lower() for k in regex_kw}
    kb_unique: list[str] = []
    seen_kb: set[str] = set()
    for raw in keybert:
        key = raw.lower().strip()
        if not key or key in seen_kb or key in regex_lower:
            continue
        seen_kb.add(key)
        kb_unique.append(raw.strip())

    return regex_kw[:18], kb_unique[:12]
