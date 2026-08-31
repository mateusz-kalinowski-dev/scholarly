-- Baseline 0 (praca.md): naiwny RAG — fixed char split, tylko embedding chunka, bez parent-child / FTS
CREATE TABLE IF NOT EXISTS baseline0_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id UUID NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    char_count INT NOT NULL,
    content TEXT NOT NULL,
    embedding VECTOR(1024),
    created_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT baseline0_chunks_paper_idx UNIQUE (paper_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS baseline0_chunks_paper_id_idx ON baseline0_chunks (paper_id);

CREATE TABLE IF NOT EXISTS baseline0_meta (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    chunk_size INT NOT NULL,
    chunk_overlap INT NOT NULL,
    embed_model TEXT NOT NULL,
    embed_dim INT NOT NULL DEFAULT 1024,
    papers_total INT,
    chunks_total INT,
    built_at TIMESTAMP DEFAULT NOW()
);
