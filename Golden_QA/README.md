# Golden QA — generator benchmarku RAGAS

## Pliki
- `generate_golden_dataset.ipynb` — budowa benchmarku (Gemini → `golden_qa`)
- `exp1_topk_ragas.ipynb` — **Eksperyment 1:** Top-K × RAGAS (final)
- `.env` — `GEMINI_API_KEY` (nie commituj!)
- `output/` — eksport JSONL, CSV, wykresy

## Eksperyment 1 (Top-K + RAGAS)

```powershell
docker compose up -d postgres api ollama processor processor-2 processor-3
cd Golden_QA
pip install -r requirements.txt
jupyter notebook exp1_topk_ragas.ipynb
```

Jeśli `ModuleNotFoundError: langchain_community.chat_models.vertexai` — uruchom ponownie `pip install -r requirements.txt` (patch w `ragas_compat.py` ładuje się z pierwszej komórki notebooka).

Ustawienia w `.env`:
- `EXPERIMENT_TOP_K=1,3,5,10,20`
- `API_BASE_URL=http://localhost:8000`
- `EXPERIMENT_SAMPLE_LIMIT=5` — pilot; `0` = wszystkie pytania z `golden_qa`
- **`RAGAS_JUDGE=ollama`** — sędzia na lokalnym Ollama (`gemma4:e2b`); **`gemini`** gdy masz quota API

Wyniki: `output/exp1_topk/rag_runs.jsonl`, `ragas_metrics_live.csv` (nadpisywany co pytanie), `ragas_per_question.jsonl`, wykresy PNG.

**Uwaga:** 100 pytań × 5 K = 500 wywołań `/chat` — trwa długo; checkpoint w `rag_runs.jsonl` pozwala wznowić.

## Uruchomienie

```powershell
cd Golden_QA
pip install -r requirements.txt
copy .env.example .env
# Uzupełnij GEMINI_API_KEY (Google AI Studio)

docker compose up -d postgres
docker compose exec -T postgres psql -U admin -d papers_db < ../services/postgres_vector/golden_qa.sql
```

Otwórz notebook w Jupyter / VS Code i uruchom wszystkie komórki.

## Tabela `golden_qa`

| Kolumna | Znaczenie |
|---------|-----------|
| `question` | Pytanie testowe |
| `ground_truth` | Wzorcowa odpowiedź |
| `reference_context` | Chunk źródłowy (prawda objawiona) |
| `chunk_id` / `arxiv_id` | Audyt |
| `question_type` | definicyjne / metodologiczne / porownawcze / wyniki |

## RAGAS

Eksport `output/golden_qa_ragas_*.jsonl`:
- `question`, `ground_truth`, `reference_contexts`

Podczas Exp.1 dopisujesz: `answer`, `contexts` (retrieved).

## .env

Użyj standardowej nazwy:
```
GEMINI_API_KEY=...
```
(stara literówka `API_KJEY` też jest obsługiwana w notebooku)
