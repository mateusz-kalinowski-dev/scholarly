-- Schema RAG zgodna z Project.md
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS papers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    arxiv_id TEXT UNIQUE NOT NULL,
    arxiv_url TEXT,
    pdf_url TEXT,
    title TEXT NOT NULL,
    summary TEXT,
    published_at TIMESTAMP,
    updated_at TIMESTAMP,
    primary_category TEXT,
    categories TEXT[],
    authors TEXT[],
    storage_path TEXT,
    source TEXT DEFAULT 'arxiv',
    parsing_status TEXT DEFAULT 'PENDING',
    chunking_status TEXT DEFAULT 'PENDING',
    embedding_status TEXT DEFAULT 'PENDING',
    paper_token_count INT,
    paper_page_count INT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_embeddings (
    paper_id UUID PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    title_embedding VECTOR(768),
    summary_embedding VECTOR(768),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id UUID REFERENCES papers(id) ON DELETE CASCADE,
    section_name TEXT,
    subsection_name TEXT,
    chunk_index INT,
    page_number INT,
    token_count INT,
    content TEXT NOT NULL,
    embedding VECTOR(768),
    created_at TIMESTAMP DEFAULT NOW()
);

-- IVFFlat: utwórz po pierwszych embeddingach (Faza B), np.:
-- CREATE INDEX chunks_embedding_idx ON chunks
--   USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS papers_arxiv_id_idx ON papers (arxiv_id);
CREATE INDEX IF NOT EXISTS chunks_paper_id_idx ON chunks (paper_id);

-- Golden QA benchmark (RAGAS)
CREATE TABLE IF NOT EXISTS golden_qa (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
    paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    arxiv_id TEXT NOT NULL,
    paper_title TEXT,
    primary_category TEXT,
    section_name TEXT,
    question TEXT NOT NULL,
    ground_truth TEXT NOT NULL,
    reference_context TEXT NOT NULL,
    question_type TEXT,
    generator_model TEXT,
    generation_status TEXT NOT NULL DEFAULT 'ok',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (chunk_id)
);

CREATE INDEX IF NOT EXISTS golden_qa_paper_id_idx ON golden_qa (paper_id);
CREATE INDEX IF NOT EXISTS golden_qa_arxiv_id_idx ON golden_qa (arxiv_id);
