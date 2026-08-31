# Scraper arXiv

Pobiera metadane prac z arXiv (kategorie CS) i wrzuca je na kolejkę RabbitMQ `paper_tasks`.

## Uruchomienie

```bash
docker compose up -d scraper
```

Entrypoint: `scraper.py` (backfill → incremental, dedup w Postgres).

## Narzędzia operacyjne

| Skrypt | Opis |
|--------|------|
| `reset_scrape_state.py` | Reset checkpointów Redis — ponowny backfill |
| `finish_backfill.py` | Wymuś tryb incremental (koniec paginacji wstecz) |
| `backfill_range.py` | Jednorazowy zrzut zakresu dat `--from-date` / `--to-date` |

Przykład:

```bash
docker compose run --rm scraper python reset_scrape_state.py
docker compose run --rm scraper python backfill_range.py --from-date 2025-01-01 --to-date 2025-01-31
```

## Konfiguracja

`.env.example` — opóźnienia API arXiv, `INITIAL_LOOKBACK_DAYS`, `POSTGRES_URL`.

Dedup: pomija prace z `embedding_status=DONE` lub trwałym `parsing_status=FAILED` w Postgres.
