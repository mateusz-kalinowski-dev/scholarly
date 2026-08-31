# Processor

Worker RabbitMQ: metadane → PDF/e-print → MinIO → parent-child chunking → embeddingi bge-m3 → Postgres.

## Uruchomienie

```bash
docker compose up -d processor processor-2 processor-3
```

Entrypoint: `processor.py` (kolejka `paper_tasks`) — **tylko parent-child** → tabela `chunks`.

## Baseline 0 (osobny pipeline)

`build_baseline0.py` **nie** jest częścią workera RabbitMQ. Uruchamiasz go ręcznie po zasileniu korpusu:

1. Czyta surowy tekst z MinIO (już zapisany przez ingest).
2. Dzieli naiwnie (`recursive_character_split`, ~1000 znaków) → tabela `baseline0_chunks`.
3. Embeduje chunki (`bge-m3`) i buduje **osobny** indeks HNSW (`--build-index`).

To inna tabela i inny indeks niż `rechunk.py --build-indexes` / `rebuild_indexes.py`, które dotyczą parent-child w `chunks`.

## Struktura

```
processor/
├── processor.py          # główny worker (Docker)
├── ingestion.py          # pobieranie PDF/e-print, zapis MinIO
├── config.py             # zmienne środowiskowe
├── pipeline/             # parse, chunk, embed, Postgres
├── baseline0/            # naiwny chunk (wariant Baseline 0 w ewaluacji)
└── *.py                  # skrypty ręczne (poniżej)
```

## Skrypty ręczne

| Skrypt | Kiedy używać |
|--------|----------------|
| `requeue_incomplete.py` | Awaria pipeline — ponowne wrzucenie prac na kolejkę |
| `stats.py` | Podgląd stanu ingestii w Postgres |
| `rechunk.py` | Reprocess jednej pracy (`--arxiv-id`) lub pierwsze indeksy (`--build-indexes`) |
| `rebuild_indexes.py` | Przebudowa HNSW / GIN / BM25 po masowym backfillu KeyBERT |
| `backfill_keywords_keybert.py` | Uzupełnienie `keywords_keybert` (profil `keybert` w compose) |
| `build_baseline0.py` | **Osobno po ingestii** — naiwny chunk → `baseline0_chunks` + własny HNSW (nie `chunks`; wymagane dla B0 w eval) |

Przykłady:

```bash
docker compose run --rm processor python stats.py
docker compose run --rm processor python requeue_incomplete.py --dry-run
docker compose run --rm processor python rechunk.py --build-indexes
docker compose run --rm processor python build_baseline0.py --ensure-schema
docker compose run --rm processor python build_baseline0.py --build-index
```

## Konfiguracja

`.env.example` — Postgres, Ollama, MinIO, rozmiary chunków (`PARENT_MAX_TOKENS`, `CHILD_CHUNK_TOKENS`, …).

Indeksy wyszukiwania odświeżane co `SEARCH_INDEX_EVERY_N_PAPERS` (domyślnie 25) ukończonych prac.

Golden QA (`Golden_QA/generate_golden_dataset.ipynb`) zapisuje `chunk_id` bezpośrednio — osobny skrypt mapowania nie jest potrzebny.
