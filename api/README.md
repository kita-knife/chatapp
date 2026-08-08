# ChatApp-PG API

FastAPI backend with LLM provider abstraction (OpenAI / Anthropic / Ollama) and SSE streaming.

## Setup

```bash
uv sync
cp .env.example .env
# edit .env to add API keys
```

## Run

```bash
uv run uvicorn app.main:app --reload --port 8000
```

## Endpoints

- `GET /api/health` – health check
- `GET /api/chat/models` – available models
- `POST /api/chat/sessions` – create session
- `GET /api/chat/sessions` – list sessions
- `GET /api/chat/sessions/{id}` – get session
- `DELETE /api/chat/sessions/{id}` – delete session
- `GET /api/chat/sessions/{id}/messages` – list messages
- `POST /api/chat/sessions/{id}/messages` – stream assistant reply (SSE)

## Providers

The provider is chosen by model prefix:

| Prefix | Provider |
|---|---|
| `gpt-*`, `o*`, `chatgpt-*` | OpenAI |
| `claude*` | Anthropic |
| `ollama:*`, `llama*`, `qwen*`, `mistral*` | Ollama (local) |
