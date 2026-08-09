# ChatApp-PG

Self-hosted AI platform: chat sessions with multi-provider LLM, per-user
preferences, agent modes (`simple` / `knowledge` / `think`), and a
per-session turn row in Postgres.

## Stack

- **Backend**: FastAPI (Python 3.12+, `uv`), SSE streaming
- **Frontend**: Vite + React + TypeScript
- **Database**: PostgreSQL 16+
- **LLM**: OpenAI-compatible endpoint (default `https://api.minimax.chat/v1`
  → `MiniMax-M3`); OpenAI / Anthropic / Ollama hooks available
- **Prompts**: all in `api/app/core/prompts.yml` (loaded at startup, optional
  hot-reload via `PROMPTS_RELOAD=true`)
- **Preferences**: per-user JSONB blob in `user_preferences` (one row / user)
- **Deployment**: Dockerfile + `railway.toml` per service

## Layout

```
chatapp-pg/
├── api/                      # FastAPI backend
│   ├── app/                  # Python source
│   │   ├── core/prompts.yml  # All user-facing prompts live here
│   │   └── ...
│   ├── Dockerfile            # API image (Python 3.12 + uv)
│   ├── railway.toml          # Railway deploy config
│   └── pyproject.toml        # uv project
├── web/                      # Vite + React SPA
│   ├── src/
│   ├── Dockerfile            # Web image (Node 22 + serve)
│   ├── railway.toml          # Railway deploy config
│   └── package.json
└── README.md
```

## Local quickstart

### Prerequisites

- Python 3.12+
- `uv` (Python package manager)
- `pnpm` (Node package manager)
- `node` 22+
- PostgreSQL 16+ reachable

### Backend

```bash
cd api
cp .env.example .env
# Edit .env: set LLM_API_KEY
uv sync
uv run python -m app.cli create-root --username root --password '<password>'  # one-time
uv run uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd web
pnpm install
pnpm dev
```

Open http://localhost:5173 and sign in.

## Deployment (Railway)

Each subdirectory (`api/`, `web/`) has a self-contained `Dockerfile` and
`railway.toml`. The recommended topology is one Railway project with three
services:

| Service | Source | Root dir | Port |
|---|---|---|---|
| `postgres` | New → Database → PostgreSQL | — | 5432 |
| `api` | GitHub repo | `api/` | `$PORT` |
| `web` | GitHub repo | `web/` | `$PORT` |

### Step-by-step

1. **Create the Railway project**
   - Dashboard → New Project → Deploy from GitHub Repo → pick
     `kita-knife/chatapp`
   - Delete the auto-created service (we'll add the right ones)

2. **Add Postgres**
   - New → Database → Add PostgreSQL
   - Railway injects `DATABASE_URL`, `PGHOST`, etc. into linked services

3. **Add the API service**
   - New → GitHub Repo (same repo)
   - Settings → **Root Directory** = `api`
   - **Variables**:

     | Key | Value |
     |---|---|
     | `DATABASE_URL` | `{{ postgres.DATABASE_URL }}` |
     | `LLM_API_BASE` | `https://api.minimax.chat/v1` |
     | `LLM_API_KEY` | your sk-… |
     | `LLM_MODEL` | `MiniMax-M3` |
     | `WEB_BASE_URL` | `<web-service>.up.railway.app` (fill after web deploys) |
     | `SESSION_COOKIE_SECURE` | `true` |
     | `SESSION_SECRET` | `python -c "import secrets;print(secrets.token_hex(32))"` |
     | `MAX_ROOT_USERS` | `4` |

4. **Add the Web service**
   - New → GitHub Repo (same repo)
   - Settings → **Root Directory** = `web`
   - **Variables**:

     | Key | Value |
     |---|---|
     | `VITE_API_BASE_URL` | `https://<api-service>.up.railway.app` |

   The Dockerfile bakes `VITE_API_BASE_URL` in at build time. After the first
   build with the wrong value, push the variable again and rebuild.

5. **Backfill `WEB_BASE_URL`**
   - Copy the web service's public URL (e.g., `https://chatapp-pg-web.up.railway.app`)
   - Set it on the API service; it restarts automatically.

6. **Create the first root user**
   - Open the API service → Shell tab
   - Run:
     ```bash
     uv run python -m app.cli create-root --username root --password '<password>'
     ```

7. **Open the web URL and sign in as root**
   - Create additional admin / user accounts in the Admin panel.

### How cross-service calls work

The web SPA talks to the API directly over HTTPS, using
`VITE_API_BASE_URL` as the base. The browser sends the `chatapp_session`
cookie; CORS on the API side allows the web origin (via `WEB_BASE_URL`).
There is no internal proxying — both services are reachable from the
public internet.

## Iteration roadmap

| # | Content | Status |
|---|---|---|
| 1 | Backend + Web skeleton, multi-provider LLM, SSE, Postgres for chat history | ✅ |
| 2 | Auth (session cookie + `create-root` CLI + role-based access) | ✅ |
| 3 | Per-user preferences (`user_preferences` JSONB), settings page | ✅ |
| 4 | Agent modes (simple / knowledge / think), prompt-loader-backed system prompts | ✅ |
| 5 | RAG (Git/Local + pgvector) | pending |
| 6 | MCP Client + default GitHub / Filesystem / Fetch | pending |
| 7 | Sandbox (Docker SDK isolation) | pending |
| 8 | Background workers (Redis + Arq) | pending |