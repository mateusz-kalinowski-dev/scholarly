from typing import Literal

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=50)
    mode: Literal["chunks", "hierarchical"] = "chunks"


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


class SearchResponse(BaseModel):
    query: str
    mode: str
    results: list[SearchHit]


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    rag: bool = True
    mode: Literal["chunks", "hierarchical"] = "hierarchical"


class SourceChunk(BaseModel):
    chunk_id: str
    paper_id: str
    arxiv_id: str
    title: str
    section_name: str | None
    content: str
    score: float


class SourcePaper(BaseModel):
    paper_id: str
    arxiv_id: str
    title: str
    arxiv_url: str | None


class ChatResponse(BaseModel):
    question: str
    answer: str
    rag_enabled: bool
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
