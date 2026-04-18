```sh
docker compose up --build # dev
docker compose -f docker-compose.yml up --build  # prod
```

# Scholarly

A full-stack application for automatically discovering, scraping, and AI-summarising academic journal papers, built for a Master's thesis.

## Architecture

```
┌─────────────┐     REST API      ┌──────────────────────────────────────────┐
│   Frontend  │ ◄───────────────► │               Backend                    │
│ React + Vite│                   │  Express.js  /api/papers  /api/graph      │
│ TypeScript  │                   │              /api/scraper                 │
└─────────────┘                   └──────┬────────────────────────────────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
             ┌──────▼──────┐    ┌───────▼──────┐   ┌────────▼───────┐
             │   Scraper   │    │  Processor   │   │   LLM Pod      │
             │  (cron pod) │    │  (worker pod)│   │  Express.js    │
             │             │    │              │   │  + Ollama      │
             │ arXiv API → │    │ MinIO PDF → │   │                │
             │ MinIO       │    │ pdf-parse → │   │ POST /summarise│
             │ + Redis Q   │    │ LLM client → │   └────────────────┘
             └─────────────┘    │ Neo4j graph  │
                                └──────────────┘

Infrastructure (via Docker Compose):
  • Neo4j  – graph database (papers, authors, topics, citations)
  • MinIO  – object storage for PDF files
  • Redis  – message queue between scraper ↔ processor
  • Ollama – local LLM runtime (llama3.2 or similar)
```

## Services

| Service     | Port        | Description                  |
| ----------- | ----------- | ---------------------------- |
| `frontend`  | 5173        | React + Vite UI              |
| `backend`   | 3000        | Express.js REST API          |
| `scraper`   | —           | Cron-based arXiv PDF scraper |
| `processor` | —           | PDF → LLM → Neo4j pipeline   |
| `llm`       | 8000        | LLM inference REST API       |
| `neo4j`     | 7474 / 7687 | Graph database               |
| `minio`     | 9000 / 9001 | Object storage               |
| `redis`     | 6379        | Message queue                |
| `ollama`    | 11434       | Local LLM runtime            |

## Quick Start

```bash
# 1. Clone and start everything
docker compose up --build

# 2. Pull an LLM model (run once)
docker exec scholarly-ollama-1 ollama pull llama3.2

# 3. Open the app
open http://localhost:5173
```

## Development

```bash
# Frontend
cd frontend
cp .env.example .env
npm install
npm run dev

# Backend
cd backend
cp .env.example .env
npm install
npm run dev

# Scraper
cd services/scraper
cp .env.example .env
npm install
npm run dev

# Processor
cd services/processor
cp .env.example .env
npm install
npm run dev

# LLM pod
cd services/llm
cp .env.example .env
npm install
npm run dev
```

## Environment Variables

Copy each `.env.example` to `.env` and adjust as needed. The defaults work out-of-the-box with `docker compose`.

## Graph Model (Neo4j)

```
(Paper)-[:AUTHORED_BY]->(Author)
(Paper)-[:HAS_TOPIC]->(Topic)
(Paper)-[:CITES]->(Paper)
```
