-- Ewaluacja koncowa: jedna tabela wynikow (pytanie x wariant).
-- Stosuj na papers_db_v2 (serwis postgres, port hosta 5445):
--   psql ... -f services/postgres/migrations/004_evaluation_runs.sql

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id            TEXT NOT NULL,
    golden_id           UUID NOT NULL REFERENCES golden_qa(id) ON DELETE CASCADE,
    variant             TEXT NOT NULL,
    question            TEXT NOT NULL,
    ground_truth        TEXT,
    reference_context   TEXT,
    question_type       TEXT,
    golden_arxiv_id     TEXT,
    golden_chunk_id     UUID,

    -- odpowiedź i retrieval
    answer              TEXT,
    retrieval_query     TEXT,
    query_rewrite       JSONB,
    retrieval_meta      JSONB,
    sources             JSONB,
    papers              JSONB,
    timings_ms          JSONB,   -- pełny dict z API (wszystkie etapy)
    raw_response        JSONB,   -- pełna odpowiedź HTTP (debug / Ragas później)

    -- metryki szybkie (bez Ragas)
    hit_at_5            SMALLINT,
    mrr                 DOUBLE PRECISION,
    idk                 BOOLEAN,
    retrieval_passes    INT,
    retrieval_accepted  BOOLEAN,
    rerank_top_score    DOUBLE PRECISION,
    llm_context_count   INT,
    alternate_query_used TEXT,
    fts_backend         TEXT,
    rerank_enabled      BOOLEAN,
    self_rag_enabled    BOOLEAN,

    -- czasy spłaszczone (wygodne SELECT / wykresy)
    timing_total_ms             DOUBLE PRECISION,
    timing_rewrite_ms           DOUBLE PRECISION,
    timing_retrieval_wall_ms    DOUBLE PRECISION,
    timing_embed_ms             DOUBLE PRECISION,
    timing_sql_ms               DOUBLE PRECISION,
    timing_hybrid_broad_ms      DOUBLE PRECISION,
    timing_hybrid_anchor_ms     DOUBLE PRECISION,
    timing_collapse_ms          DOUBLE PRECISION,
    timing_rerank_ms            DOUBLE PRECISION,
    timing_self_rag_grade_ms    DOUBLE PRECISION,
    timing_llm_ms               DOUBLE PRECISION,
    client_latency_ms           DOUBLE PRECISION,

    api_status          TEXT NOT NULL DEFAULT 'ok',
    error_message       TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT evaluation_runs_variant_chk CHECK (variant IN (
        'baseline0',
        'baseline1',
        'eksperyment1-gin',
        'eksperyment1-bm25',
        'eksperyment2'
    )),
    CONSTRAINT evaluation_runs_batch_golden_variant_uq
        UNIQUE (batch_id, golden_id, variant)
);

CREATE INDEX IF NOT EXISTS evaluation_runs_batch_idx
    ON evaluation_runs (batch_id);
CREATE INDEX IF NOT EXISTS evaluation_runs_variant_idx
    ON evaluation_runs (variant);
CREATE INDEX IF NOT EXISTS evaluation_runs_golden_idx
    ON evaluation_runs (golden_id);
CREATE INDEX IF NOT EXISTS evaluation_runs_status_idx
    ON evaluation_runs (api_status);
CREATE INDEX IF NOT EXISTS evaluation_runs_hit_idx
    ON evaluation_runs (batch_id, variant, hit_at_5);

COMMENT ON TABLE evaluation_runs IS
    'Wyniki zbierania odpowiedzi /api/research/*/chat na Golden QA (przed Ragas).';
COMMENT ON COLUMN evaluation_runs.timings_ms IS
    'Pełny timings_ms z API: rewrite, hybrid_broad/anchor, sql, embed, rerank, llm, …';
COMMENT ON COLUMN evaluation_runs.batch_id IS
    'Identyfikator kampanii zbierania (np. eval-2026-07-19); UNIQUE z golden_id+variant.';
