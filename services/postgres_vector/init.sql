-- Aktywacja rozszerzenia pgvector w bazie danych
CREATE EXTENSION IF NOT EXISTS vector;

-- Możesz tu od razu przygotować tabelę, jeśli chcesz zacząć od zera
CREATE TABLE IF NOT EXISTS papers (
    id VARCHAR(50) PRIMARY KEY,
    title TEXT NOT NULL,
    published_date TIMESTAMP,
    summary_raw TEXT,
    tldr_ai TEXT,
    pdf_minio_url TEXT,
    embedding vector(768), -- Wymiar dla modelu nomic-embed-text
    status VARCHAR(20) DEFAULT 'NEW'
);