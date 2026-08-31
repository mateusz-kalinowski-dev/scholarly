# Postgres (ParadeDB)

Jedyna baza projektu Scholarly — ParadeDB + pgvector, parent-child chunks, hybrid GIN/BM25 (bge-m3, 1024d).

## Pliki

| Plik | Opis |
|------|------|
| `init.sql` | Schema przy pierwszym starcie kontenera |
| `migrations/` | Migracje nakładane ręcznie na istniejące klastry |

## Uruchomienie

```bash
docker compose up -d postgres
```

- **W Dockerze:** `postgresql://admin:admin@postgres:5432/papers_db_v2`
- **Z hosta:** `postgresql://admin:admin@localhost:5445/papers_db_v2`

## Migracje

```bash
docker compose exec -T postgres psql -U admin -d papers_db_v2 \
  -f /docker-entrypoint-initdb.d/../migrations/001_keywords_keybert.sql
```

Lub z hosta:

```bash
psql "postgresql://admin:admin@localhost:5445/papers_db_v2" \
  -f services/postgres/migrations/004_evaluation_runs.sql
```

## Indeksy wyszukiwania

Po zasileniu korpusu processor odświeża HNSW/GIN/BM25 co N prac. Ręcznie:

```bash
docker compose run --rm processor python rechunk.py --build-indexes
```
