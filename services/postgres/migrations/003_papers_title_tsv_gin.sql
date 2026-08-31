-- Indeks GIN na tytule papieru (anchor pass bez ILIKE seq scan)
CREATE INDEX IF NOT EXISTS papers_title_tsv_gin_idx
    ON papers USING gin (to_tsvector('english', coalesce(title, '')));
