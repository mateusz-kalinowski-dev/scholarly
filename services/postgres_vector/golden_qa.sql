-- Golden QA benchmark (RAGAS: question, ground_truth, reference_context)
-- Uruchom na istniejącej bazie:
--   docker compose exec -T postgres psql -U admin -d papers_db < services/postgres_vector/golden_qa.sql

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
CREATE INDEX IF NOT EXISTS golden_qa_question_type_idx ON golden_qa (question_type);
