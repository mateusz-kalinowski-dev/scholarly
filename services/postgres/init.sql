-- Scholarly: ParadeDB (pg_search + pgvector), parent-child chunks, hybrid retrieval
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_search;

CREATE TYPE chunk_role AS ENUM ('parent', 'child');

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
    schema_version TEXT NOT NULL DEFAULT 'v2',
    legacy_paper_id UUID,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS paper_embeddings (
    paper_id UUID PRIMARY KEY REFERENCES papers(id) ON DELETE CASCADE,
    title_embedding VECTOR(1024),
    summary_embedding VECTOR(1024),
    embed_model TEXT DEFAULT 'bge-m3',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    parent_id UUID REFERENCES chunks(id) ON DELETE CASCADE,
    chunk_role chunk_role NOT NULL,
    section_name TEXT,
    subsection_name TEXT,
    chunk_index INT NOT NULL DEFAULT 0,
    child_index INT,
    sacred_type TEXT,
    page_number INT,
    token_count INT,
    content TEXT NOT NULL,
    keywords TEXT[] NOT NULL DEFAULT '{}',
    keywords_keybert TEXT[] NOT NULL DEFAULT '{}',
    search_text TEXT NOT NULL DEFAULT '',
    text_search tsvector,
    embedding VECTOR(1024),
    strategy TEXT,
    legacy_chunk_id UUID,
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT chunks_role_parent CHECK (
        (chunk_role = 'parent' AND parent_id IS NULL)
        OR (chunk_role = 'child' AND parent_id IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS papers_arxiv_id_idx ON papers (arxiv_id);
CREATE INDEX IF NOT EXISTS papers_embedding_status_idx ON papers (embedding_status);
CREATE INDEX IF NOT EXISTS chunks_paper_id_idx ON chunks (paper_id);
CREATE INDEX IF NOT EXISTS chunks_parent_id_idx ON chunks (parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS chunks_role_idx ON chunks (chunk_role);

-- Golden QA (chunk_id uzupełniane po ingestii parent-child)
CREATE TABLE IF NOT EXISTS golden_qa (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chunk_id UUID REFERENCES chunks(id) ON DELETE SET NULL,
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
    legacy_chunk_id UUID,
    migration_status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS golden_qa_legacy_chunk_idx
    ON golden_qa (legacy_chunk_id)
    WHERE legacy_chunk_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS golden_qa_paper_id_idx ON golden_qa (paper_id);
CREATE INDEX IF NOT EXISTS golden_qa_arxiv_id_idx ON golden_qa (arxiv_id);
CREATE INDEX IF NOT EXISTS golden_qa_migration_status_idx ON golden_qa (migration_status);

CREATE OR REPLACE FUNCTION chunks_sync_text_search() RETURNS trigger AS $$
BEGIN
    NEW.search_text := trim(both from
        NEW.content || ' ' ||
        coalesce(array_to_string(NEW.keywords, ' '), '') || ' ' ||
        coalesce(array_to_string(NEW.keywords_keybert, ' '), '')
    );
    NEW.text_search := to_tsvector('english', NEW.search_text);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER chunks_text_search_trg
    BEFORE INSERT OR UPDATE OF content, keywords, keywords_keybert ON chunks
    FOR EACH ROW EXECUTE FUNCTION chunks_sync_text_search();

-- Indeksy wyszukiwania tworzone PO zasileniu danych (rechunk.py --build-indexes):
--   HNSW na embedding (child)
--   GIN na text_search (child)
--   BM25 pg_search na id, content, search_text
