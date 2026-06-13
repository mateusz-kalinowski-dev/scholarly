# EDA — Scholarly

Notebook: **`scholarly_eda.ipynb`**

## Uruchomienie

```powershell
cd scholarly
docker compose up -d postgres
pip install -r EDA/requirements.txt
jupyter notebook EDA/scholarly_eda.ipynb
```

W VS Code / Cursor: otwórz `EDA/scholarly_eda.ipynb` i wybierz kernel Pythona z zainstalowanymi pakietami.

## Wyniki

Po uruchomieniu powstaje folder `EDA/figures/`:
- wykresy PNG (pipeline, daty, kategorie, chunki),
- `eda_summary.csv` — tabela KPI do pracy.

## Połączenie

Domyślnie: `postgresql+psycopg://admin:admin@localhost:5444/papers_db`

Inny host/port:
```powershell
$env:POSTGRES_URL="postgresql+psycopg://admin:admin@localhost:5444/papers_db"
```
