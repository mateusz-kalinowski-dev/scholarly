### 1. CEL PROJEKTU
Główny cel:
Stworzenie systemu typu RAG (Retrieval-Augmented Generation) dla prac naukowych z arXiv, który:
- wyszukuje semantycznie fragmenty papers,
- odpowiada na pytania użytkownika,
- redukuje halucynacje modeli LLM,
- porównuje jakość: LLM-only vs RAG.

### 2. ARCHITEKTURA SYSTEMU
                         ┌────────────────────┐
                         │     arXiv API      │
                         └─────────┬──────────┘
                                   ↓
                    ┌──────────────────────────┐
                    │      arXiv Scraper       │
                    │                          │
                    │ - metadata               │
                    │ - PDF links              │
                    │ - source tar.gz links    │
                    └─────────┬────────────────┘
                              ↓
                    ┌──────────────────────────┐
                    │      RabbitMQ Queue      │
                    │       papers.raw         │
                    └─────────┬────────────────┘
                              ↓
               ┌──────────────────────────────────┐
               │        Ingestion Service         │
               │                                  │
               │ - zapis metadata do PostgreSQL   │
               │ - pobranie PDF                   │
               │ - pobranie source tar.gz         │
               │ - upload do MinIO                │
               └──────────────┬───────────────────┘
                              ↓
                    ┌──────────────────────────┐
                    │        PostgreSQL        │
                    │      papers metadata     │
                    └──────────────────────────┘
                              ↓
                    ┌──────────────────────────┐
                    │          MinIO           │
                    │ PDFs + source files      │
                    └─────────┬────────────────┘
                              ↓
                    ┌──────────────────────────┐
                    │     Parsing Service      │
                    │                          │
                    │ - extract tar.gz         │
                    │ - parse LaTeX/TXT        │
                    │ - fallback PDF parsing   │
                    │ - section detection      │
                    │ - cleaning               │
                    └─────────┬────────────────┘
                              ↓
                    ┌──────────────────────────┐
                    │   Structure Analyzer     │
                    │                          │
                    │ - detect sections        │
                    │ - detect subsections     │
                    │ - estimate token count   │
                    │ - classify paper size    │
                    └─────────┬────────────────┘
                              ↓
                    ┌──────────────────────────┐
                    │    Adaptive Chunker      │
                    │                          │
                    │ - section-aware chunks   │
                    │ - semantic chunking      │
                    │ - hierarchical chunking  │
                    │ - overlap handling       │
                    └─────────┬────────────────┘
                              ↓
                    ┌──────────────────────────┐
                    │   Embedding Service      │
                    │                          │
                    │ Ollama                   │
                    │ nomic-embed-text         │
                    └─────────┬────────────────┘
                              ↓
                    ┌──────────────────────────┐
                    │       pgvector DB        │
                    │                          │
                    │ papers embeddings        │
                    │ chunks embeddings        │
                    └─────────┬────────────────┘
                              ↓
                    ┌──────────────────────────┐
                    │    Retrieval Engine      │
                    │                          │
                    │ - paper retrieval        │
                    │ - chunk retrieval        │
                    │ - hybrid retrieval       │
                    │ - reranking              │
                    └─────────┬────────────────┘
                              ↓
                    ┌──────────────────────────┐
                    │        RAG API           │
                    │                          │
                    │ FastAPI                  │
                    │ /chat                    │
                    │ /search                  │
                    └─────────┬────────────────┘
                              ↓
                    ┌──────────────────────────┐
                    │    Ollama + Gemma/Qwen   │
                    │                          │
                    │ grounded generation      │
                    └─────────┬────────────────┘
                              ↓
                           RESPONSE

### 3. STACK TECHNOLOGICZNY
#### Warstwa	Technologiczna

| Warstwa          | Technologia           |
| ---------------- | --------------------- |
| LLM              | Ollama + Gemma/Qwen   |
| Embeddings       | nomic-embed-text      |
| Vector DB        | pgvector              |
| Metadata DB      | PostgreSQL            |
| Storage          | MinIO (S3-compatible) |
| Queue            | RabbitMQ              |
| API              | FastAPI               |
| Parsing          | PyMuPDF / GROBID      |
| Containerization | Docker Compose        |
| (opcjonalnie)    | Kafka + Spark         |


### 4. ETAP 1 — POZYSKANIE DANYCH

##### 4.1 Pobieranie papers z arXiv
Zadania
pobieranie metadata o:
- title
- authors
- categories
- summary
- published_date
pobieranie txt/LateX linków

##### 4.2 Storage

txt/LateX przewchowywane w minio w bucket `papers`

Tabela:
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE papers (
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

CREATE TABLE paper_embeddings (
    paper_id UUID PRIMARY KEY REFERENCES papers(id),
    title_embedding VECTOR(768),
    summary_embedding VECTOR(768),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id UUID REFERENCES papers(id),
    section_name TEXT,
    subsection_name TEXT,
    chunk_index INT,
    page_number INT,
    token_count INT,
    content TEXT NOT NULL,
    embedding VECTOR(768),
    created_at TIMESTAMP DEFAULT NOW()
);
```
Należy też potem dodać index vector

### 5. ETAP 2 — PARSING DOKUMENTÓW
##### 5.1 PDF → tekst
Opcje:
- Regex,  użycie re


##### 5.2 Ekstrakcja struktury

Rozpoznawanie:
- section
- subsection
- abstract
- introduction
- methods
- results
- conclusion
- references
- bibliography
- appendix

##### 5.3 Czyszczenie tekstu

Usunięcie:
- nadmiar whitespace
- references noise
- broken line breaks
- latex artifacts
- LaTeX commands
- equations noise,

### 6. ETAP 3 — ADAPTIVE CHUNKING
##### 6.1 Analiza dokumentu
Obliczanie:
- liczba tokenów
- liczba sekcji
- długość sekcji
- długość papera

##### 6.2 Strategia chunkingu
SHORT PAPERS
- 1–3 chunki

STANDARD PAPERS
- section-aware chunking
- 800 tokens
- 150 overlap

LONG PAPERS
- hierarchical chunking

Semantic chunking

Chunk boundaries:

based on sections,
paragraphs,
semantic transitions.

##### 6.3 Metadata chunków

Przykład chunka:
```json
{
  "paper_id": "...",
  "section": "Methods",
  "subsection": "Optimization",
  "chunk_index": 5,
  "content": "...",
  "page": 12,
  "chunking_strategy": "section-aware"
}
```
### 7. ETAP 4 — EMBEDDINGS
##### 7.1 Model embeddingowy

Model: `nomic-embed-text`
uruchamiany przez Ollama

Paper-level
- title,
- summary.

Chunk-level
- parsed chunks.
##### 7.2 Generacja embeddingów

Każdy chunk:
- chunk → embedding vector

##### 7.3 Tabela pgvector
taka jak powyżej zdefiniowana
```sql
CREATE TABLE chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id UUID REFERENCES papers(id),
    section_name TEXT,
    subsection_name TEXT,
    chunk_index INT,
    page_number INT,
    token_count INT,
    content TEXT NOT NULL,
    embedding VECTOR(768),
    created_at TIMESTAMP DEFAULT NOW()
);
```
##### 7.4 Indeksy
```sql
CREATE INDEX chunks_embedding_idx
ON chunks
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

### 8. ETAP 5 — RETRIEVAL SYSTEM
##### 8.1 Query pipeline

Hierarchical Retrieval
    Step 1 — paper retrieval
query → summary embeddings
    Step 2 — chunk retrieval
query → chunk embeddings

wewnątrz najlepszych papers.

Lub od razu po chunkach gdyby summary były niewystarczające

User query: "What is Flash Attention?"
##### 8.2 Embedding pytania
question → embedding
##### 8.3 Similarity search
```sql
SELECT *
FROM chunks
ORDER BY embedding <-> query_embedding
LIMIT 5;
```
8.4 Retrieval output

Top-k chunków:
- najbardziej podobnych semantycznie.

### 9. ETAP 6 — RAG PIPELINE
##### 9.1 Prompt assembly

Budowa prompta:

SYSTEM:
You are a scientific assistant.

CONTEXT:
[retrieved chunks]

QUESTION:
[user question]

ANSWER:

##### 9.2 Generacja odpowiedzi

LLM: `Gemma4`
przez: Ollama

##### 9.3 Response
Zwracaj:
- answer
- source chunks
- source papers
- citations.

### 10. ETAP 7 — BACKEND API
##### 10.1 Endpoints
Search
POST /search

semantic search papers.

Chat
POST /chat

RAG QA.

Papers
GET /papers/{id}

### 11. ETAP 8 — FRONTEND
Możliwe funkcje
- chat with papers
- semantic search
- similar papers
- explain paper
- summarize paper

### 12. ETAP 9 — EKSPERYMENTY BADAWCZE
##### 12.1 Baseline
LLM-only
question → `Gemma4`
bez retrieval.

##### 12.2 RAG
question → retrieval → `Gemma4`

##### 12.3 Porównania
Metryki:
- Metryka	- Opis
- Accuracy	- poprawność odpowiedzi
- Hallucination rate	- liczba błędnych faktów
- Groundedness	- zgodność z dokumentami
- Retrieval precision	- jakość chunków
- Latency	- czas odpowiedzi
##### 12.4 Dodatkowe eksperymenty
Porównanie:
- embedding models
- chunk sizes
- top-k retrieval
- hybrid search vs vector search

### 13. ETAP 10 — HYBRID SEARCH (opcjonalne)

Połączenie:
BM25 + vector search

### 14. ETAP 11 — RERANKING (opcjonalne)
Cross-encoder
Lepsze sortowanie retrieved chunks.

### 15. ETAP 12 — CITATION RAG

Odpowiedzi:
According to paper X...

### 16. ETAP 13 — DEPLOYMENT

Docker Compose
Kontenery:
- postgres
- pgvector
- ollama
- api
- frontend
- scrapper
- processor

### 17. ETAP 14 — MOŻLIWE ROZSZERZENIA
- Advanced features
- paper recommendation engine
- citation graph
- knowledge graph
- multi-agent retrieval
- streaming ingestion
- Kafka + Spark embeddings pipeline

### 18. FINALNY EFEKT

System umożliwia:

✔ semantic search papers
✔ question answering over arXiv
✔ grounded scientific answers
✔ comparison of LLM vs RAG
✔ retrieval evaluation
✔ reduction of hallucinations

### 19. PROPOZYCJA TEMATU PRACY
Opcje
„Retrieval-Augmented Generation for Scientific Knowledge Retrieval using arXiv Papers”

lub

„Evaluation of Retrieval-Augmented LLM Systems for Scientific Question Answering”

lub

„Semantic Retrieval and Question Answering over Scientific Literature using RAG Architecture”