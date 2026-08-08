# ChatApp-PG

Self-hosted AI platform with multi-provider LLM chat. Simple skeleton — iteration 1.

## Stack

- **Backend**: FastAPI (Python 3.12+, `uv`) — OpenAI / Anthropic / Ollama providers with SSE streaming
- **Frontend**: Vite + React + TypeScript
- **Database**: PostgreSQL 16 (in `infra/docker-compose.yml`)
- **No auth, no Docker production, no MCP/RAG/sandbox yet** — these arrive in later iterations

## Layout

```
chatapp-pg/
├── api/        # FastAPI backend
├── web/        # Vite + React SPA
├── infra/      # docker-compose (Postgres only)
└── README.md
```

## Quickstart

### 1. Start Postgres

```bash
cd infra
docker compose up -d
```

### 2. Start the backend

```bash
cd api
cp .env.example .env
# fill in OPENAI_API_KEY / ANTHROPIC_API_KEY (or leave Ollama defaults)
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Verify:

```bash
curl http://localhost:8000/api/health
# {"status":"ok"}
```

### 3. Start the frontend

```bash
cd web
pnpm install
pnpm dev
```

Open http://localhost:5173 and start chatting.

## Endpoints

- `GET  /api/health` – health
- `GET  /api/chat/models` – list available models
- `POST /api/chat/sessions` – create a chat session
- `GET  /api/chat/sessions` – list sessions
- `POST /api/chat/sessions/{id}/messages` – send a message; **response is SSE**
- `GET  /api/chat/sessions/{id}/messages` – list messages

## Provider routing

The provider is selected by model prefix:

| Model prefix | Provider |
|---|---|
| `gpt-*`, `o*` | OpenAI |
| `claude*` | Anthropic |
| `ollama:*`, `llama*`, `qwen*`, `mistral*` | Ollama (local) |

## Iteration roadmap

| # | Content |
|---|---|
| 1 (current) | Backend + Web skeleton, LLM providers, SSE, Postgres for chat history |
| 2 | Auth (session cookie + first-time setup) |
| 3 | Redis + Arq worker (long job isolation) |
| 4 | RAG (Git/Local + pgvector) |
| 5 | MCP Client + default GitHub / Filesystem / Fetch |
| 6 | Sandbox (Docker SDK isolation) |
| 7 | Plugins + deploy hardening (Caddy + CI) |
