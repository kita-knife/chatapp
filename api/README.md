# ChatApp-PG API

FastAPI backend that exposes multi-provider LLM chat via [agno](https://github.com/agno-agi/agno), with SSE streaming for assistant replies.

## Setup

```bash
uv sync
cp .env.example .env
# edit .env to set LLM_API_KEY (and any optional alt providers)
```

Required Postgres (one-time):

```bash
PGPASSWORD=postgreswsl psql -h localhost -p 5433 -U postgres -c "CREATE DATABASE chatapp;"
```

(Tables are auto-created on the first startup.)

## Run

```bash
uv run uvicorn app.main:app --reload --port 8000
```

Verify:

```bash
curl http://localhost:8000/api/health
# {"status":"ok"}
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health |
| `GET` | `/api/chat/models` | Models available in the UI |
| `POST` | `/api/chat/sessions` | Create session |
| `GET` | `/api/chat/sessions` | List sessions |
| `GET` | `/api/chat/sessions/{id}` | Get one session |
| `DELETE` | `/api/chat/sessions/{id}` | Delete session |
| `GET` | `/api/chat/sessions/{id}/messages` | List messages |
| `POST` | `/api/chat/sessions/{id}/messages` | Send a message — **response is SSE** |

### SSE event format

```text
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

See `.env.example` for the full template. The key variables are:

| Variable | Default | Description |
|---|---|---|
| `LLM_API_BASE` | `https://api.minimax.chat/v1` | OpenAI-compatible endpoint |
| `LLM_API_KEY` | _(empty)_ | API key for the endpoint above |
| `LLM_MODEL` | `MiniMax-M3` | Default model |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | _(empty)_ | Optional OpenAI hook |
| `ANTHROPIC_API_KEY` | _(empty)_ | Optional Anthropic hook |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Optional Ollama hook |
| `POSTGRES_*` | `localhost:5433` / `chatapp` / `postgres` / `postgreswsl` | DB connection |

## Layout

```
api/
├── app/
│   ├── main.py                 # FastAPI entrypoint
│   ├── core/
│   │   ├── config.py           # pydantic-settings
│   │   └── db.py               # SQLAlchemy async engine
│   ├── api/
│   │   └── router.py           # /api router
│   └── modules/
│       └── chat/
│           ├── models.py       # ChatSession, ChatMessage
│           ├── routes.py       # /api/chat/*
│           ├── service.py      # History + dispatch
│           └── providers.py    # agno provider layer
├── pyproject.toml
└── .env.example
```
