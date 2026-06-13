export type RetrievalMode = "chunks" | "hierarchical";
export type QueryStrategy = "classic" | "rewrite";
export type ApiVersion = "v1" | "v2";

export interface SearchHit {
  chunk_id: string;
  paper_id: string;
  arxiv_id: string;
  title: string;
  arxiv_url: string | null;
  section_name: string | null;
  subsection_name: string | null;
  chunk_index: number | null;
  content: string;
  score: number;
  content_original?: string | null;
}

export interface SearchHitV2 {
  child_id: string;
  parent_id: string;
  paper_id: string;
  arxiv_id: string;
  title: string;
  arxiv_url: string | null;
  section_name: string | null;
  subsection_name: string | null;
  child_snippet: string;
  content: string;
  vector_distance: number;
  text_score: number;
  score: number;
}

export interface SearchResponse {
  query: string;
  mode: string;
  query_strategy?: QueryStrategy;
  retrieval_query?: string | null;
  user_language?: string | null;
  results: SearchHit[];
}

export interface RetrievalMetaV2 {
  rerank_enabled: boolean;
  self_rag_enabled: boolean;
  candidate_limit: number;
  child_candidates?: number | null;
  parent_candidates?: number | null;
  parents_reranked?: number | null;
  rerank_top_score?: number | null;
  llm_context_count?: number | null;
  retrieval_passes?: number;
  retrieval_confidence?: number | null;
  alternate_query_used?: string | null;
  answer_verified?: boolean | null;
  accepted?: boolean;
}

export interface SearchResponseV2 {
  query: string;
  query_strategy?: QueryStrategy;
  retrieval_query?: string | null;
  user_language?: string | null;
  retrieval?: RetrievalMetaV2 | null;
  results: SearchHitV2[];
}

export interface SourceChunk {
  chunk_id: string;
  paper_id: string;
  arxiv_id: string;
  title: string;
  section_name: string | null;
  content: string;
  score: number;
  content_original?: string | null;
}

export interface SourceChunkV2 {
  child_id: string;
  parent_id: string;
  paper_id: string;
  arxiv_id: string;
  title: string;
  section_name: string | null;
  child_snippet: string;
  content: string;
  score: number;
  vector_distance: number;
  text_score: number;
}

export interface SourcePaper {
  paper_id: string;
  arxiv_id: string;
  title: string;
  arxiv_url: string | null;
}

export interface ChatResponse {
  question: string;
  answer: string;
  rag_enabled: boolean;
  query_strategy?: QueryStrategy;
  retrieval_query?: string | null;
  user_language?: string | null;
  sources: SourceChunk[];
  papers: SourcePaper[];
}

export interface ChatResponseV2 {
  question: string;
  answer: string;
  rag_enabled: boolean;
  query_strategy?: QueryStrategy;
  retrieval_query?: string | null;
  user_language?: string | null;
  retrieval?: RetrievalMetaV2 | null;
  sources: SourceChunkV2[];
  papers: SourcePaper[];
}
