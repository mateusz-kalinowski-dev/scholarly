from typing import Literal

from pydantic import BaseModel, Field


QueryStrategy = Literal["classic", "rewrite"]


class SearchHitV2(BaseModel):
    child_id: str
    parent_id: str
    paper_id: str
    arxiv_id: str
    title: str
    arxiv_url: str | None
    section_name: str | None
    subsection_name: str | None
    child_snippet: str
    content: str
    vector_distance: float
    text_score: float
    hybrid_score: float
    rerank_score: float | None = None
    score: float


class ChatRequestResearch(BaseModel):
    """Badania ablacyjne — zawsze RAG + query rewrite."""

    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=15)


class MetadataFiltersOut(BaseModel):
    arxiv_id: str | None = None
    author: str | None = None
    year: int | None = None
    primary_category: str | None = None


class QueryRewriteOut(BaseModel):
    semantic_query: str
    keywords: list[str] = Field(default_factory=list)
    anchor_entities: list[str] = Field(default_factory=list)
    metadata_filters: MetadataFiltersOut
    intent: Literal["chitchat", "general_knowledge", "paper_search"]
    user_language: str


class RetrievalMetaV2(BaseModel):
    research_variant: str | None = None
    rerank_enabled: bool
    self_rag_enabled: bool
    fts_backend: str | None = None
    candidate_limit: int
    child_candidates: int | None = None
    parent_candidates: int | None = None
    parents_reranked: int | None = None
    rerank_top_score: float | None = None
    llm_context_count: int | None = None
    retrieval_passes: int = 1
    retrieval_confidence: float | None = None
    alternate_query_used: str | None = None
    answer_verified: bool | None = None
    accepted: bool = True
    timings_ms: dict[str, float] | None = None


class SearchResponseV2(BaseModel):
    query: str
    query_strategy: QueryStrategy = "classic"
    retrieval_query: str | None = None
    user_language: str | None = None
    query_rewrite: QueryRewriteOut | None = None
    retrieval: RetrievalMetaV2 | None = None
    results: list[SearchHitV2]


class SourceChunkV2(BaseModel):
    child_id: str
    parent_id: str
    paper_id: str
    arxiv_id: str
    title: str
    section_name: str | None
    child_snippet: str
    content: str
    score: float
    hybrid_score: float
    rerank_score: float | None = None
    vector_distance: float
    text_score: float


class SourcePaper(BaseModel):
    paper_id: str
    arxiv_id: str
    title: str
    arxiv_url: str | None


class ChatResponseV2(BaseModel):
    question: str
    answer: str
    research_variant: str | None = None
    rag_enabled: bool = True
    query_strategy: QueryStrategy = "classic"
    retrieval_query: str | None = None
    user_language: str | None = None
    query_rewrite: QueryRewriteOut | None = None
    retrieval: RetrievalMetaV2 | None = None
    timings_ms: dict[str, float] | None = None
    sources: list[SourceChunkV2]
    papers: list[SourcePaper]
