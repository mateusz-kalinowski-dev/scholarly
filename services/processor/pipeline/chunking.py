"""Parent-child chunking: Rodzic (szeroki kontekst) + Dzieci (embed + search)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from config import (
    CHILD_CHUNK_TOKENS,
    CHILD_OVERLAP_TOKENS,
    MIN_CHILD_TOKENS,
    PARENT_MAX_TOKENS,
)
from .keywords import extract_keywords
from .sanitize import strip_legacy_sacred_placeholders
from .parsing import (
    SKIP_SECTIONS,
    SacredBlock,
    SectionBlock,
    clean_text,
    estimate_tokens,
    extract_sacred_blocks,
)


@dataclass
class ChildChunkDraft:
    content: str
    child_index: int
    token_count: int
    sacred_type: str | None = None
    keywords: list[str] = field(default_factory=list)


@dataclass
class ParentChunkDraft:
    section_name: str | None
    subsection_name: str | None
    chunk_index: int
    content: str
    token_count: int
    children: list[ChildChunkDraft] = field(default_factory=list)
    strategy: str = "parent-child-v2"


def _split_by_tokens(text: str, chunk_size: int, overlap: int) -> list[str]:
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


def _mask_sacred_gaps(text: str, sacred: list[SacredBlock]) -> str:
    """Zastępuje święte bloki spacjami — reszta idzie do sliding window."""
    if not sacred:
        return text
    parts: list[str] = []
    cursor = 0
    for b in sacred:
        parts.append(text[cursor : b.start])
        parts.append(" ")
        cursor = b.end
    parts.append(text[cursor:])
    return "".join(parts)


def _build_children_for_parent(
    parent_content: str,
    *,
    paper_title: str,
    section_name: str | None,
    subsection_name: str | None,
) -> list[ChildChunkDraft]:
    parent_content = strip_legacy_sacred_placeholders(parent_content)
    sacred = extract_sacred_blocks(parent_content)
    prose = clean_text(_mask_sacred_gaps(parent_content, sacred))
    children: list[ChildChunkDraft] = []
    idx = 0

    for block in sacred:
        if estimate_tokens(block.content) < MIN_CHILD_TOKENS:
            continue
        kw = extract_keywords(
            block.content,
            paper_title=paper_title,
            section_name=section_name,
            subsection_name=subsection_name,
            sacred_type=block.sacred_type,
        )
        children.append(
            ChildChunkDraft(
                content=block.content,
                child_index=idx,
                token_count=estimate_tokens(block.content),
                sacred_type=block.sacred_type,
                keywords=kw,
            )
        )
        idx += 1

    for piece in _split_by_tokens(prose, CHILD_CHUNK_TOKENS, CHILD_OVERLAP_TOKENS):
        piece = piece.strip()
        if estimate_tokens(piece) < MIN_CHILD_TOKENS:
            continue
        kw = extract_keywords(
            piece,
            paper_title=paper_title,
            section_name=section_name,
            subsection_name=subsection_name,
        )
        children.append(
            ChildChunkDraft(
                content=piece,
                child_index=idx,
                token_count=estimate_tokens(piece),
                keywords=kw,
            )
        )
        idx += 1

    if not children and parent_content.strip():
        fallback = clean_text(parent_content)
        if fallback:
            kw = extract_keywords(
                fallback,
                paper_title=paper_title,
                section_name=section_name,
                subsection_name=subsection_name,
            )
            children.append(
                ChildChunkDraft(
                    content=fallback,
                    child_index=0,
                    token_count=estimate_tokens(fallback),
                    keywords=kw,
                )
            )
    return children


def _section_to_parents(section: SectionBlock, start_index: int) -> list[ParentChunkDraft]:
    raw = section.content.strip()
    if not raw:
        return []

    content = clean_text(raw)
    if not content:
        return []

    tokens = estimate_tokens(content)
    if tokens <= PARENT_MAX_TOKENS:
        parents_content = [content]
    else:
        parents_content = _split_by_tokens(content, PARENT_MAX_TOKENS, CHILD_OVERLAP_TOKENS)

    result: list[ParentChunkDraft] = []
    for i, pc in enumerate(parents_content):
        pc = pc.strip()
        if not pc:
            continue
        result.append(
            ParentChunkDraft(
                section_name=section.section_name,
                subsection_name=section.subsection_name,
                chunk_index=start_index + i,
                content=pc,
                token_count=estimate_tokens(pc),
            )
        )
    return result


def build_parent_child_chunks(
    sections: list[SectionBlock],
    *,
    paper_title: str = "",
) -> list[ParentChunkDraft]:
    parents: list[ParentChunkDraft] = []
    idx = 0

    for section in sections:
        if section.section_name.lower() in SKIP_SECTIONS:
            continue
        batch = _section_to_parents(section, idx)
        if batch:
            children = _build_children_for_parent(
                section.content,
                paper_title=paper_title,
                section_name=section.section_name,
                subsection_name=section.subsection_name,
            )
            batch[0].children = children
        parents.extend(batch)
        idx += len(batch)

    if not parents:
        combined = clean_text("\n\n".join(s.content for s in sections))
        if combined:
            p = ParentChunkDraft(
                section_name="Document",
                subsection_name=None,
                chunk_index=0,
                content=combined,
                token_count=estimate_tokens(combined),
            )
            p.children = _build_children_for_parent(
                "\n\n".join(s.content for s in sections),
                paper_title=paper_title,
                section_name="Document",
                subsection_name=None,
            )
            parents.append(p)

    return parents
