import os

CS_CATEGORIES = [
    "cs.AI", "cs.AR", "cs.CC", "cs.CE", "cs.CG", "cs.CL", "cs.CR", "cs.CV",
    "cs.CY", "cs.DB", "cs.DC", "cs.DL", "cs.DM", "cs.DS", "cs.ET", "cs.FL",
    "cs.GL", "cs.GR", "cs.GT", "cs.HC", "cs.IR", "cs.IT", "cs.LG", "cs.LO",
    "cs.MA", "cs.MM", "cs.MS", "cs.NA", "cs.NE", "cs.NI", "cs.OH", "cs.OS",
    "cs.PF", "cs.PL", "cs.PO", "cs.RO", "cs.SC", "cs.SD", "cs.SE", "cs.SI",
    "cs.SY",
]

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@rabbitmq:5672/")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
POSTGRES_URL = os.getenv(
    "POSTGRES_URL", "postgresql://admin:admin@postgres:5432/papers_db"
)

CHECKPOINT_KEY = "scraper:last_paper_timestamp"
SEEN_IDS_KEY = "scraper:seen_arxiv_ids"
BACKFILL_DONE_KEY = "scraper:backfill_done"
BACKFILL_CURSOR_KEY = "scraper:backfill_start"
INCREMENTAL_CURSOR_KEY = "scraper:incremental_start"

ARXIV_USER_AGENT = os.getenv(
    "ARXIV_USER_AGENT",
    "mailto:student@uczelnia.pl - ScholarlyRAG/1.0 (Polite Scraper)",
)
ARXIV_PAGE_SIZE = int(os.getenv("ARXIV_PAGE_SIZE", "200"))
ARXIV_REQUEST_DELAY = float(os.getenv("ARXIV_REQUEST_DELAY", "5.0"))
# 0 = w jednym cyklu paginuj aż do cutoff / końca wyników (szybki zrzut miesiąca)
ARXIV_MAX_PAGES_PER_RUN = int(os.getenv("ARXIV_MAX_PAGES_PER_RUN", "0"))
INITIAL_LOOKBACK_DAYS = int(os.getenv("INITIAL_LOOKBACK_DAYS", "30"))
# Po zakończonym cyklu — krótka przerwa, potem kolejny cykl jeśli backfill nie skończony
SCRAPER_INTERVAL_SECONDS = int(os.getenv("SCRAPER_INTERVAL_SECONDS", "120"))
ARXIV_MAX_RETRIES = int(os.getenv("ARXIV_MAX_RETRIES", "6"))
# arXiv API zwykle odmawia przy start>=10000 (HTTP 500) — dalej tylko incremental od góry
ARXIV_MAX_START_OFFSET = int(os.getenv("ARXIV_MAX_START_OFFSET", "10000"))
# Co ile wrzuconych na kolejkę zapisujemy checkpoint (Postgres i tak deduplikuje po arxiv_id)
CHECKPOINT_COMMIT_EVERY = int(os.getenv("CHECKPOINT_COMMIT_EVERY", "25"))
# Przy starcie kontenera: usuń checkpoint i wymuś backfill od INITIAL_LOOKBACK_DAYS
SCRAPER_RESET_ON_START = os.getenv("SCRAPER_RESET_ON_START", "false").lower() in (
    "1",
    "true",
    "yes",
)
