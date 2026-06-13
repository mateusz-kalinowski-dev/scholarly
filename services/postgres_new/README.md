# Scholarly DB v2 (ParadeDB + parent-child)

## Co się zmienia

| v1 (`postgres` :5444) | v2 (`postgres_v2` :5445) |
|------------------------|---------------------------|
| `nomic-embed-text` 768d | `bge-m3` **1024d** |
| płaskie chunki | **parent** (kontekst LLM) + **child** (search/embed) |
| IVFFlat | **HNSW** + **GIN** (`text_search`) + **BM25** (`pg_search`) |
| `clean_text` usuwał math | v2 **zachowuje** równania/tabele |

MinIO (`papers` bucket) **bez zmian** — rechunk czyta `storage_path`.

## Kroki migracji

### 1. Backup v1

```powershell
.\scripts\backup_postgres.ps1
```

### 2. Uruchom postgres_v2

```powershell
docker compose up -d postgres_v2
```

Poczekaj na healthcheck (`pg_isready`). Pierwszy start tworzy `papers_db_v2` z `init.sql`.

### 3. Migruj metadane (papers + golden_qa)

```powershell
$env:POSTGRES_URL="postgresql://admin:admin@localhost:5444/papers_db"
$env:POSTGRES_V2_URL="postgresql://admin:admin@localhost:5445/papers_db_v2"
py -3 scripts\migrate_metadata_v2.py
```

### 4. Rechunk z MinIO (nowy pipeline)

```powershell
cd services\processor
$env:POSTGRES_V2_URL="postgresql://admin:admin@localhost:5445/papers_db_v2"
$env:MINIO_ENDPOINT="localhost:9000"
$env:LLM_BASE_URL="http://localhost:11434"
$env:EMBED_MODEL_V2="bge-m3"
py -3 rechunk_v2.py --limit 10
```

### 5. Indeksy hybrid (po pierwszej partii chunków)

```powershell
py -3 rechunk_v2.py --build-indexes
```

## Hybrydowe zapytanie (szkic SQL)

Szukaj w **dzieciach**, zwracaj **rodziców** do LLM — patrz `new_version.md` § Krok 6.

## API

Na razie API nadal wskazuje na v1. Po zasileniu v2 podmienisz `POSTGRES_URL` w `docker-compose` dla `api` / `processor`.
