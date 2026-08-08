# ChatApp-PG

Self-hosted AI platform. Minimal skeleton — iteration 1.

## Stack

- **Backend**: FastAPI (Python 3.12+, `uv`) — multi-provider LLM via [agno](https://github.com/agno-agi/agno), SSE streaming
- **Frontend**: Vite + React + TypeScript
- **Database**: PostgreSQL 17 (existing instance on `localhost:5433`)
- **LLM**: OpenAI-compatible endpoint (default `https://api.minimax.chat/v1` → `MiniMax-M3`); OpenAI / Anthropic / Ollama hooks available
- **No auth, no Docker production, no MCP/RAG/sandbox yet** — these arrive in later iterations

## Layout

```
chatapp-pg/
├── api/        # FastAPI backend
├── web/        # Vite + React SPA
├── infra/      # docker-compose (reserved for future use)
└── README.md
```

## Prerequisites

- Python 3.12+
- `uv` (Python package manager)
- `pnpm` (Node package manager)
- `node` 22+
- PostgreSQL 17 reachable on `localhost:5433` (db `chatapp`, user `postgres`, password `postgreswsl`)

```bash
# create the database (one-time)
PGPASSWORD=postgreswsl psql -h localhost -p 5433 -U postgres -c "CREATE DATABASE chatapp;"
```

## Quickstart

### 1. Backend

```bash
cd api
cp .env.example .env
# edit .env: set LLM_API_KEY (and any alt providers you want)
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Tables are auto-created on first startup. Verify:

```bash
curl http://localhost:8000/api/health
# {"status":"ok"}
```

### 2. Frontend

```bash
cd web
pnpm install
pnpm dev
```

Open http://localhost:5173 and start chatting.

## API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/chat/models` | Models available in the UI |
| `POST` | `/api/chat/sessions` | Create a chat session |
| `GET` | `/api/chat/sessions` | List sessions |
| `GET` | `/api/chat/sessions/{id}` | Get one session |
| `DELETE` | `/api/chat/sessions/{id}` | Delete session |
| `GET` | `/api/chat/sessions/{id}/messages` | List messages |
| `POST` | `/api/chat/sessions/{id}/messages` | Send a message — **response is SSE** |

### SSE event format

```json
data: {"delta": "你好", "finish_reason": null, "error": null}

data: {"delta": "", "finish_reason": "stop", "error": null}
```

## Provider routing

agno is used as the provider layer. The provider is selected by model prefix:

| Model prefix | Provider |
|---|---|
| `minimax*` | MiniMax OpenAI-compatible (default) |
| `gpt-*`, `o*`, `chatgpt-*` | OpenAI |
| `claude*` | Anthropic |
| `ollama:*`, `llama*`, `qwen*`, `mistral*` | Ollama (local) |

If the model doesn't match any prefix, the request falls back to the configured MiniMax endpoint.

## Config

`api/.env` (see `api/.env.example` for the full template):

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | Environment name |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | Backend bind |
| `WEB_BASE_URL` | `http://localhost:5173` | CORS allow-list |
| `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `localhost` / `5433` / `chatapp` / `postgres` / `postgreswsl` | DB connection |
| `LLM_API_BASE` | `https://api.minimax.chat/v1` | OpenAI-compatible endpoint |
| `LLM_API_KEY` | _(empty)_ | API key for the endpoint above |
| `LLM_MODEL` | `MiniMax-M3` | Default model |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | _(empty)_ | Optional OpenAI hook |
| `ANTHROPIC_API_KEY` | _(empty)_ | Optional Anthropic hook |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Optional Ollama hook |
| `OPENAI_DEFAULT_MODEL` / `ANTHROPIC_DEFAULT_MODEL` / `OLLAMA_DEFAULT_MODEL` | `gpt-4o-mini` / `claude-3-5-sonnet-latest` / `llama3.2` | Default models used in the UI picker |

## Iteration roadmap

| # | Content | Status |
|---|---|---|
| 1 (current) | Backend + Web skeleton, multi-provider LLM (agno), SSE, Postgres for chat history | ✅ done |
| 2 | Auth (session cookie + first-time setup) | pending |
| 3 | Redis + Arq worker (long job isolation) | pending |
| 4 | RAG (Git/Local + pgvector) | pending |
| 5 | MCP Client + default GitHub / Filesystem / Fetch | pending |
| 6 | Sandbox (Docker SDK isolation) | pending |
| 7 | Plugins + deploy hardening (Caddy + CI) | pending |
