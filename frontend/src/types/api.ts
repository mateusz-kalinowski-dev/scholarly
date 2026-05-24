export type RetrievalMode = "chunks" | "hierarchical";

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
}

export interface SearchResponse {
  query: string;
  mode: string;
  results: SearchHit[];
}

export interface SourceChunk {
  chunk_id: string;
  paper_id: string;
  arxiv_id: string;
  title: string;
  section_name: string | null;
  content: string;
  score: number;
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
  sources: SourceChunk[];
  papers: SourcePaper[];
}

export interface ApiError {
  detail: string;
}
