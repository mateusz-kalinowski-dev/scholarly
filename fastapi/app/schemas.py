from typing import Literal

from pydantic import BaseModel, Field


QueryStrategy = Literal["classic", "rewrite"]


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=50)
    mode: Literal["chunks", "hierarchical"] = "chunks"
    query_strategy: QueryStrategy = "classic"


class SearchHit(BaseModel):
    chunk_id: str
    paper_id: str
    arxiv_id: str
    title: str
    arxiv_url: str | None
    section_name: str | None
    subsection_name: str | None
    chunk_index: int | None
    content: str
    score: float
    content_original: str | None = None


class SearchResponse(BaseModel):
    query: str
    mode: str
    query_strategy: QueryStrategy = "classic"
    retrieval_query: str | None = None
    user_language: str | None = None
    results: list[SearchHit]


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    rag: bool = True
    mode: Literal["chunks", "hierarchical"] = "hierarchical"
    query_strategy: QueryStrategy = "classic"


class SourceChunk(BaseModel):
    chunk_id: str
    paper_id: str
    arxiv_id: str
    title: str
    section_name: str | None
    content: str
    score: float
    content_original: str | None = None


class SourcePaper(BaseModel):
    paper_id: str
    arxiv_id: str
    title: str
    arxiv_url: str | None


class ChatResponse(BaseModel):
    question: str
    answer: str
    rag_enabled: bool
    query_strategy: QueryStrategy = "classic"
    retrieval_query: str | None = None
    user_language: str | None = None
    sources: list[SourceChunk]
    papers: list[SourcePaper]


class PaperResponse(BaseModel):
    id: str
    arxiv_id: str
    arxiv_url: str | None
    pdf_url: str | None
    title: str
    summary: str | None
    authors: list[str]
    categories: list[str]
    primary_category: str | None
    published_at: str | None
    storage_path: str | None
    parsing_status: str | None
    chunking_status: str | None
    embedding_status: str | None
    paper_token_count: int | None
    chunk_count: int


# --- v2 hybrid (parent-child, bge-m3) ---


class SearchRequestV2(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=30)
    query_strategy: QueryStrategy = "classic"


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


class RetrievalMetaV2(BaseModel):
    rerank_enabled: bool
    self_rag_enabled: bool
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


class SearchResponseV2(BaseModel):
    query: str
    query_strategy: QueryStrategy = "classic"
    retrieval_query: str | None = None
    user_language: str | None = None
    retrieval: RetrievalMetaV2 | None = None
    results: list[SearchHitV2]


class ChatRequestV2(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=15)
    rag: bool = True
    query_strategy: QueryStrategy = "classic"


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


class ChatResponseV2(BaseModel):
    question: str
    answer: str
    rag_enabled: bool
    query_strategy: QueryStrategy = "classic"
    retrieval_query: str | None = None
    user_language: str | None = None
    retrieval: RetrievalMetaV2 | None = None
    sources: list[SourceChunkV2]
    papers: list[SourcePaper]
