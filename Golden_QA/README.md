# Golden QA

Generator zestawu pytań referencyjnych — notebook `generate_golden_dataset.ipynb`.

## Wymagania

```bash
docker compose up -d postgres api ollama
```

Schema `golden_qa` jest w `services/postgres/init.sql`.

## Konfiguracja

Skopiuj `.env.example` → `.env` i uzupełnij `GEMINI_API_KEY`.

Połączenie z hosta: `localhost:5445/papers_db_v2`
