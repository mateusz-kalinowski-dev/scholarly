"""Query router: semantic query, keywords, anchors, metadata filters, intent."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from app.services.metadata_filters import MetadataFilters
from app.services.rag import LLMError, generate_answer

logger = logging.getLogger(__name__)

QueryIntent = Literal["chitchat", "general_knowledge", "paper_search"]

REWRITE_PROMPT = """You are an expert query router for Scholarly, an English scientific paper RAG system over arXiv CS papers.

The database stores paper metadata (title, summary, authors, published_at, arxiv_id, primary_category), chunk text with embeddings, and precomputed title/summary embeddings (bge-m3). Retrieval uses semantic vectors AND lexical keyword/BM25 search.

Analyze the USER MESSAGE and output ONLY one valid JSON object. No markdown, no commentary, no code fences.

Rules:
1. English for search: semantic_query, keywords, and anchor_entities MUST be English. Translate concepts from any user language.
2. semantic_query: one or two concise English sentences for dense semantic search (embedding). Include core concepts, methods, datasets, metrics. Do NOT put author names, years, or arXiv IDs here — use metadata_filters. Avoid the phrase "corresponding levels of support based on evaluation results" — use "support levels from evaluation results" instead.
3. keywords: 3–8 English terms or short phrases for lexical / BM25 search. Discriminative terms only (model names, datasets, metrics). No question words. Empty array [] for chitchat.
4. anchor_entities: 0–5 proper nouns — acronyms, model/dataset names (EUVP, UIESNN). Subset of or aligned with keywords. Empty [] if none.
5. metadata_filters — extract ONLY if explicit or unambiguous; use null when unknown (not empty string):
   - arxiv_id: e.g. "2605.08376" or null
   - author: family name or as user wrote, or null
   - year: integer or null
   - primary_category: e.g. "cs.CV", "cs.LG" or null
6. intent — exactly one of: "chitchat", "general_knowledge", "paper_search"
7. user_language: language for the final answer (e.g. "Polish", "English")

Output JSON schema:
{{
  "semantic_query": "<string>",
  "keywords": ["<string>"],
  "anchor_entities": ["<string>"],
  "metadata_filters": {{
    "arxiv_id": null,
    "author": null,
    "year": null,
    "primary_category": null
  }},
  "intent": "chitchat | general_knowledge | paper_search",
  "user_language": "<string>"
}}

USER MESSAGE:
{question}
"""


@dataclass
class QueryRewriteResult:
    semantic_query: str
    keywords: list[str]
    anchor_entities: list[str]
    metadata_filters: MetadataFilters
    intent: QueryIntent
    user_language: str
    original_question: str

    @property
    def retrieval_query(self) -> str:
        """Backward-compatible alias for semantic_query."""
        return self.semantic_query

    @property
    def lexical_query(self) -> str:
        if self.keywords:
            return " ".join(self.keywords)
        return self.semantic_query

    def anchors_for_retrieval(self, question: str) -> list[str]:
        if self.anchor_entities:
            return self.anchor_entities
        from app.services.retrieval_v2 import anchor_terms_from_text

        return anchor_terms_from_text(question)

    def to_api_dict(self) -> dict:
        return {
            "semantic_query": self.semantic_query,
            "keywords": self.keywords,
            "anchor_entities": self.anchor_entities,
            "metadata_filters": {
                "arxiv_id": self.metadata_filters.arxiv_id,
                "author": self.metadata_filters.author,
                "year": self.metadata_filters.year,
                "primary_category": self.metadata_filters.primary_category,
            },
            "intent": self.intent,
            "user_language": self.user_language,
        }


def query_rewrite_to_out(result: QueryRewriteResult):
    from app.schemas import QueryRewriteOut

    return QueryRewriteOut(**result.to_api_dict())


def _parse_metadata(raw: dict | None) -> MetadataFilters:
    if not raw or not isinstance(raw, dict):
        return MetadataFilters()
    year = raw.get("year")
    if year is not None:
        try:
            year = int(year)
        except (TypeError, ValueError):
            year = None
    arxiv_id = raw.get("arxiv_id")
    author = raw.get("author")
    category = raw.get("primary_category")
    return MetadataFilters(
        arxiv_id=(arxiv_id or "").strip() or None,
        author=(author or "").strip() or None,
        year=year,
        primary_category=(category or "").strip() or None,
    )


def _parse_keywords(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    for item in raw:
        if isinstance(item, str):
            term = item.strip()
            if term and term not in out:
                out.append(term)
    return out[:12]


def _fallback_keywords(semantic_query: str) -> list[str]:
    terms = re.findall(r"[A-Za-z0-9][A-Za-z0-9._-]{1,}", semantic_query)
    skip = {
        "the", "and", "for", "with", "from", "that", "this", "are", "was", "were",
        "how", "what", "when", "where", "which", "their", "than", "into", "about",
    }
    out: list[str] = []
    for t in terms:
        if len(t) > 2 and t.lower() not in skip and t not in out:
            out.append(t)
        if len(out) >= 8:
            break
    return out


def _fallback_result(question: str) -> QueryRewriteResult:
    return QueryRewriteResult(
        semantic_query=question,
        keywords=_fallback_keywords(question),
        anchor_entities=[],
        metadata_filters=MetadataFilters(),
        intent="paper_search",
        user_language="English",
        original_question=question,
    )


def _parse_rewrite_json(raw: str, fallback_question: str) -> QueryRewriteResult:
    text = raw.strip()
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        text = match.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Nie udało się sparsować JSON rewrite: %s", raw[:200])
        return _fallback_result(fallback_question)

    semantic = (data.get("semantic_query") or data.get("retrieval_query") or "").strip()
    language = (data.get("user_language") or "").strip()
    intent_raw = (data.get("intent") or "paper_search").strip().lower()
    intent: QueryIntent = (
        intent_raw
        if intent_raw in ("chitchat", "general_knowledge", "paper_search")
        else "paper_search"
    )
    keywords = _parse_keywords(data.get("keywords"))
    anchors = _parse_keywords(data.get("anchor_entities"))
    metadata = _parse_metadata(data.get("metadata_filters"))

    if not semantic and intent == "paper_search":
        semantic = fallback_question
    if not keywords and semantic and intent == "paper_search":
        keywords = _fallback_keywords(semantic)
    if not language:
        language = "English"

    if intent == "paper_search" and not semantic:
        return _fallback_result(fallback_question)

    return QueryRewriteResult(
        semantic_query=semantic,
        keywords=keywords,
        anchor_entities=anchors,
        metadata_filters=metadata,
        intent=intent,
        user_language=language,
        original_question=fallback_question,
    )


async def rewrite_query_for_retrieval(question: str) -> QueryRewriteResult:
    prompt = REWRITE_PROMPT.format(question=question)
    try:
        raw = await generate_answer(prompt)
    except LLMError:
        logger.exception("Rewrite query — fallback do oryginału")
        return _fallback_result(question)
    return _parse_rewrite_json(raw, question)


def classic_query_rewrite(question: str) -> QueryRewriteResult:
    """Tryb classic — bez LLM routera; pytanie jako semantic_query."""
    return _fallback_result(question)
