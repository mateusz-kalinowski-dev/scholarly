# Scholarly

System RAG nad pracami arXiv — praca magisterska.  
Pipeline: ingestia arXiv → parent-child chunking → indeksy ParadeDB/pgvector → API FastAPI → ewaluacja w notebookach Jupyter.

---

## Wymagania

- **Docker** + Docker Compose
- **NVIDIA GPU** — Ollama (embed + LLM) i reranker w API korzystają z CUDA
- **Python 3.12+** — notebooki ewaluacyjne i Golden QA (kernel lokalnie, poza Dockerem)
- Opcjonalnie: klucze **OpenAI** (DeepEval, pilot Self-RAG) i **Gemini** (generacja Golden QA)

---

## Uruchomienie

### 1. Konfiguracja

```bash
git clone <repo>
cd scholarly
```

Skopiuj pliki `.env.example` → `.env` w katalogach, których używasz:

| Katalog | Po co |
|---------|--------|
| `evaluation/` | batch eval, Ragas, DeepEval |
| `Golden_QA/` | `GEMINI_API_KEY` |
| `.env` (root) | opcjonalnie `OPENAI_API_KEY` dla API / DeepEval |

Domyślne wartości w compose działają bez zmian dla Postgres, Ollama i MinIO.

### 2. Stack minimalny (ewaluacja RAG)

Wystarczy do notebooków `evaluation/01`–`08` — zakłada istniejący korpus i tabelę `golden_qa` w bazie:

```bash
docker compose up -d postgres ollama ollama-init api
```

- API docs: http://localhost:8000/docs  
- Health: http://localhost:8000/health  

Pierwsze uruchomienie Ollama pobiera modele `gemma4:e2b` i `bge-m3` (kilka–kilkanaście minut).

### 3. Pełny pipeline ingestii (opcjonalnie)

Budowa korpusu od zera — scraper + procesory:

```bash
docker compose up -d postgres ollama ollama-init
docker compose up -d scraper processor processor-2 processor-3
# gdy korpus jest zasilony — API:
docker compose up -d api
```

**Baseline 0** (wariant ablacyjny) wymaga osobnej tabeli:

```bash
docker compose run --rm processor python build_baseline0.py --ensure-schema
docker compose run --rm processor python build_baseline0.py
docker compose run --rm processor python build_baseline0.py --build-index
```

**Indeksy wyszukiwania** (pierwszy raz lub po dużej zmianie danych):

```bash
docker compose run --rm processor python rechunk.py --build-indexes
```

### 4. Zatrzymanie

```bash
docker compose down          # kontenery
docker compose down -v       # + wolumeny (usuwa bazę!)
```

---

## Architektura

```
  Scraper ──► RabbitMQ ──► Processor (×3)
       │                         │
       └──────── Postgres ◄──────┘ (chunki, embeddingi)
                    │
       MinIO (PDF)  │     Ollama (bge-m3 + gemma4:e2b)
                    ▼
              FastAPI :8000
         /api/research/{variant}/chat
                    │
         evaluation/ + Golden_QA/ (notebooki)
```

### Serwisy Docker

| Serwis | Port (host) | Rola |
|--------|-------------|------|
| `postgres` | **5445** | ParadeDB + pgvector — chunki, `golden_qa`, `evaluation_runs` |
| `api` | **8000** | FastAPI — 5 wariantów ablacyjnych RAG |
| `ollama` | **11434** | Embeddingi (`bge-m3`) i LLM (`gemma4:e2b`) |
| `minio` | 9000 / 9001 | Storage PDF/e-print |
| `rabbitmq` | 5672 / 15672 | Kolejka zadań processorów |
| `redis` | 6379 | Checkpoint scrapera |
| `scraper` | — | arXiv → kolejka `paper_tasks` |
| `processor`, `processor-2`, `processor-3` | — | parse → chunk → embed → Postgres |
| `keybert-backfill` | — | opcjonalny profil `--profile keybert` |

### Warianty API (`/api/research/.../chat`)

| Wariant | Opis skrócony |
|---------|----------------|
| `baseline0` | Naiwny chunk ~1000 zn., tylko vector |
| `baseline1` | Parent-child, vector + filtr tytuł/summary |
| `eksperyment1-gin` | Hybrid vector + GIN + rerank |
| `eksperyment1-bm25` | Hybrid vector + BM25 + rerank |
| `eksperyment2` | Jak BM25 + Self-RAG |
| `eksperyment2-openai` | Pilot — Self-RAG z LLM OpenAI (poza główną ewaluacją) |

### Baza danych

Jedna instancja — nazwa w volume: `papers_db_v2`.

| Kontekst | URL |
|----------|-----|
| W Dockerze | `postgresql://admin:admin@postgres:5432/papers_db_v2` |
| Z hosta (notebooki) | `postgresql://admin:admin@localhost:5445/papers_db_v2` |

Schema: `services/postgres/init.sql`, migracje: `services/postgres/migrations/`.

---

## Zarządzanie komponentami

### API

```bash
docker compose up -d api
docker compose logs -f api
curl http://localhost:8000/health
```

Test w Swagger: `POST /api/research/eksperyment2/chat` z body `{"question": "...", "top_k": 5}`.

### Ingestia (scraper + processor)

```bash
docker compose up -d scraper processor processor-2 processor-3
docker compose logs -f processor
docker compose run --rm processor python stats.py
```

| Operacja | Komenda |
|----------|---------|
| Ponowna kolejka (FAILED/PENDING) | `docker compose run --rm processor python requeue_incomplete.py` |
| Reset checkpoint scrapera | `docker compose run --rm scraper python reset_scrape_state.py` |
| Koniec backfillu → incremental | `docker compose run --rm scraper python finish_backfill.py` |
| Reprocess jednej pracy | `docker compose run --rm processor python rechunk.py --arxiv-id <id>` |
| Przebudowa indeksów | `docker compose run --rm processor python rebuild_indexes.py` |
| KeyBERT keywords (opcjonalnie) | `docker compose --profile keybert run --rm keybert-backfill` |

Szczegóły: `services/scraper/README.md`, `services/processor/README.md`.

### Golden QA (zbiór testowy)

Generacja pytań referencyjnych do tabeli `golden_qa` (Gemini):

```bash
cd Golden_QA
copy .env.example .env    # GEMINI_API_KEY
pip install -r requirements.txt
docker compose up -d postgres
jupyter notebook generate_golden_dataset.ipynb
```

### EDA korpusu

```bash
cd EDA
pip install -r requirements.txt
docker compose up -d postgres
jupyter notebook scholarly_eda.ipynb
```

Wyniki: `EDA/figures/`, `EDA/tables/` (gitignore — generujesz lokalnie).

---

## Ewaluacja RAG

Pipeline notebooków w `evaluation/` — każdy **samodzielny** (logika w komórkach, bez zewnętrznych skryptów `.py`).

**Przygotowanie:**

```bash
cd evaluation
copy .env.example .env
pip install -r requirements.txt
docker compose up -d postgres ollama ollama-init api
```

Ustaw w `.env`: `EVAL_BATCH_ID`, ewentualnie `OPENAI_API_KEY` (DeepEval / notebook 06).

### Kolejność notebooków

| # | Notebook | Cel |
|---|----------|-----|
| **01** | `01_run_research_endpoints.ipynb` | Woła API dla 5 wariantów × Golden QA → zapis do `evaluation_runs` |
| **02** | `02_ragas_scoring.ipynb` | Metryki Ragas (LLM judge via Ollama) |
| **03** | `03_offline_analysis.ipynb` | Analiza offline: hit@k, MRR, IDK — bez dodatkowego LLM |
| **04** | `04_deepeval_scoring.ipynb` | Metryki DeepEval (GPT judge) |
| **05** | `05_deepeval_analysis.ipynb` | Wykresy i tabele z DeepEval |
| **06** | `06_openai_selfrag_pilot.ipynb` | Pilot Self-RAG + OpenAI (opcjonalny) |
| **07** | `07_latency_analysis.ipynb` | Rozkład czasów odpowiedzi (`timings_ms`) |
| **08** | `08_ablacje_istotnosc.ipynb` | Porównania par wariantów, istotność statystyczna |

Wyniki zapisywane do Postgres (`evaluation_runs`) i/lub `evaluation/output/` (gitignore).

**Typowy flow:** `01` → `03` + (`02` lub `04`→`05`) → `07` → `08`.

---

## Struktura repozytorium

```
scholarly/
├── docker-compose.yml
├── fastapi/              # API research
├── services/
│   ├── postgres/         # schema + migracje
│   ├── scraper/
│   └── processor/
├── Golden_QA/            # generator golden_qa
├── EDA/                  # analiza eksploracyjna korpusu
└── evaluation/           # notebooki 01–08
```

---

## Licencja / autor

Projekt magisterski — repozytorium do odtwarzalności badań RAG nad arXiv.
