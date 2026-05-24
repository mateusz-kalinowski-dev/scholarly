"""Adaptacyjny chunking: SHORT / STANDARD / LONG."""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from config import (
    LONG_PAPER_MIN_TOKENS,
    SHORT_MAX_CHUNKS,
    SHORT_PAPER_MAX_TOKENS,
    STANDARD_CHUNK_TOKENS,
    STANDARD_OVERLAP_TOKENS,
)
from parsing import SKIP_SECTIONS, SectionBlock, estimate_tokens


class PaperSize(str, Enum):
    SHORT = "short"
    STANDARD = "standard"
    LONG = "long"


class ChunkStrategy(str, Enum):
    WHOLE = "whole"
    SECTION_AWARE = "section-aware"
    HIERARCHICAL = "hierarchical"


@dataclass
class TextChunk:
    section_name: str | None
    subsection_name: str | None
    chunk_index: int
    content: str
    token_count: int
    strategy: str


def classify_paper(total_tokens: int) -> PaperSize:
    if total_tokens <= SHORT_PAPER_MAX_TOKENS:
        return PaperSize.SHORT
    if total_tokens >= LONG_PAPER_MIN_TOKENS:
        return PaperSize.LONG
    return PaperSize.STANDARD


def _split_by_tokens(
    text: str,
    chunk_size: int,
    overlap: int,
) -> list[str]:
    words = text.split()
    if not words:
        return []

    approx_words_per_token = 1 / 1.3
    size_words = max(1, int(chunk_size * approx_words_per_token))
    overlap_words = max(0, int(overlap * approx_words_per_token))
    step = max(1, size_words - overlap_words)

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = min(len(words), start + size_words)
        piece = " ".join(words[start:end])
        if piece.strip():
            chunks.append(piece)
        if end >= len(words):
            break
        start += step
    return chunks


def _chunk_short(sections: list[SectionBlock]) -> list[TextChunk]:
    combined = "\n\n".join(s.content for s in sections if s.section_name.lower() not in SKIP_SECTIONS)
    if not combined.strip():
        combined = "\n\n".join(s.content for s in sections)

    parts = _split_by_tokens(
        combined,
        chunk_size=max(estimate_tokens(combined) // SHORT_MAX_CHUNKS, 400),
        overlap=0,
    )
    if not parts:
        parts = [combined] if combined.strip() else []

    parts = parts[:SHORT_MAX_CHUNKS]
    result: list[TextChunk] = []
    for i, content in enumerate(parts):
        result.append(
            TextChunk(
                section_name="Document",
                subsection_name=None,
                chunk_index=i,
                content=content,
                token_count=estimate_tokens(content),
                strategy=ChunkStrategy.WHOLE.value,
            )
        )
    return result


def _chunk_section_sliding(
    section: SectionBlock,
    strategy: str,
    chunk_size: int = STANDARD_CHUNK_TOKENS,
    overlap: int = STANDARD_OVERLAP_TOKENS,
) -> list[tuple[str, str | None, str]]:
    pieces = _split_by_tokens(section.content, chunk_size, overlap)
    return [(section.section_name, section.subsection_name, p) for p in pieces]


def _chunk_standard(sections: list[SectionBlock]) -> list[TextChunk]:
    pieces: list[tuple[str, str | None, str]] = []
    for sec in sections:
        if sec.section_name.lower() in SKIP_SECTIONS:
            continue
        pieces.extend(_chunk_section_sliding(sec, ChunkStrategy.SECTION_AWARE.value))

    result: list[TextChunk] = []
    for i, (sname, subname, content) in enumerate(pieces):
        result.append(
            TextChunk(
                section_name=sname,
                subsection_name=subname,
                chunk_index=i,
                content=content,
                token_count=estimate_tokens(content),
                strategy=ChunkStrategy.SECTION_AWARE.value,
            )
        )
    return result


def _chunk_long(sections: list[SectionBlock]) -> list[TextChunk]:
    """Długie prace: najpierw dzielenie dużych sekcji na akapity, potem sliding window."""
    pieces: list[tuple[str, str | None, str]] = []
    for sec in sections:
        if sec.section_name.lower() in SKIP_SECTIONS:
            continue

        sec_tokens = estimate_tokens(sec.content)
        if sec_tokens > STANDARD_CHUNK_TOKENS * 2:
            paragraphs = [p.strip() for p in re_split_paragraphs(sec.content) if p.strip()]
            for para in paragraphs:
                sub = SectionBlock(sec.section_name, sec.subsection_name, para)
                pieces.extend(
                    _chunk_section_sliding(sub, ChunkStrategy.HIERARCHICAL.value)
                )
        else:
            pieces.extend(_chunk_section_sliding(sec, ChunkStrategy.HIERARCHICAL.value))

    result: list[TextChunk] = []
    for i, (sname, subname, content) in enumerate(pieces):
        result.append(
            TextChunk(
                section_name=sname,
                subsection_name=subname,
                chunk_index=i,
                content=content,
                token_count=estimate_tokens(content),
                strategy=ChunkStrategy.HIERARCHICAL.value,
            )
        )
    return result


def re_split_paragraphs(text: str) -> list[str]:
    return re.split(r"\n\s*\n+", text)


def build_chunks(sections: list[SectionBlock], total_tokens: int) -> list[TextChunk]:
    size = classify_paper(total_tokens)
    if size == PaperSize.SHORT:
        return _chunk_short(sections)
    if size == PaperSize.LONG:
        return _chunk_long(sections)
    return _chunk_standard(sections)
