# ChatApp-PG

Self-hosted AI platform: chat sessions with multi-provider LLM streaming,
per-user preferences, three agent modes (`simple` / `knowledge` / `think`),
and per-session turn rows in Postgres.

Built for a single-tenant self-hosted deployment with Dockerfiles for
[Railway](https://railway.app), but runs anywhere that has Python 3.12+ and
Node 22+.

---

## Features

- **Chat sessions** with SSE streaming; each turn is one row
  (`user_content` + `assistant_content` + status + token counts).
- **Multi-provider LLM** routed by model prefix (OpenAI-compatible
  endpoints out of the box, plus Anthropic / Ollama hooks).
- **Three agent modes**:
  - `simple` — direct LLM call
  - `knowledge` — augments the system prompt with retrieved context
    (RAG source is a pluggable hook; default returns `[]`)
  - `think` — Chinese CoT prompt + higher `max_tokens`
- **Per-user preferences** persisted in `user_preferences` (JSONB blob) and
  merged on every request (`default_mode`, `default_model`, `ui_language`).
- **Title auto-generation**: immediate fallback (truncated user message)
  on first turn + background LLM refinement after the stream finishes.
- **Externalized prompts**: all user-facing prompts live in
  `api/app/core/prompts.yml`; no prompt is hard-coded in code.
- **Auth + RBAC**: cookie-session login, three roles (`root` / `admin` /
  `user`), role-scoped endpoints, root can create additional admins/users.
- **Thinking-block filter**: server-side `<think>...</think>` is
  stripped from both the stream and the persisted content (MiniMax-M3
  emits it by default).

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2 (async), `uv` package manager |
| LLM abstraction | [agno](https://github.com/agno-agi/agno) for provider factory + resolution; OpenAI client directly for streaming (so we can capture `usage` tokens) |
| Frontend | Vite 6, React 18, TypeScript, TanStack Query, React Router 7 |
| Database | PostgreSQL 16+ (uses `pgvector` later) |
| SSE | FastAPI `StreamingResponse` with `text/event-stream` |
| Deploy | Multi-stage Dockerfile per service; `railway.toml` per service |

## Project layout

```
chatapp-pg/
├── api/
│   ├── app/
│   │   ├── core/                  # config, db, security, prompts.yml, prompts.py
│   │   ├── api/router.py          # /api/* mount
│   │   ├── cli/                   # `python -m app.cli` (create-root)
│   │   └── modules/
│   │       ├── auth/             # users, auth_sessions, login/me/logout
│   │       │   └── users/         # root-only user CRUD
│   │       ├── chat/             # sessions, messages (turns), providers
│   │       └── users_prefs/      # preferences table + endpoints
│   ├── Dockerfile                # Python 3.12-slim + uv + libpq
│   ├── railway.toml              # Railway service config
│   └── pyproject.toml
├── web/
│   ├── src/
│   │   ├── api/client.ts          # fetch wrapper, all API methods
│   │   ├── app/                   # router, AppShell
│   │   ├── auth/                  # login page, useAuth hook
│   │   ├── chat/                  # ChatPage
│   │   ├── rag/ mcp/ settings/    # placeholder pages (future)
│   │   ├── admin/                 # AdminUsersPage (root only)
│   │   ├── components/            # ChatInput, ChatTurn, SessionList
│   │   ├── hooks/useChat.ts       # main chat state + actions
│   │   └── styles/global.css
│   ├── Dockerfile                # Node 22 multi-stage + serve
│   ├── railway.toml
│   └── package.json
└── README.md
```

## Database schema

```text
users (PK uuid)
  username      UNIQUE
  password_hash (bcrypt)
  role          ('root' | 'admin' | 'user')
  created_at, last_login_at

auth_sessions (PK uuid)
  user_id FK users(id) ON DELETE CASCADE
  token (UNIQUE)
  expires_at

chat_sessions (PK uuid)
  owner_id FK users(id) ON DELETE CASCADE
  title, model
  created_at, updated_at

chat_messages (PK uuid)   ← ONE ROW PER TURN
  session_id FK chat_sessions(id) ON DELETE CASCADE
  user_content, assistant_content
  user_tokens_in, assistant_tokens_out
  status ('pending'|'streaming'|'complete'|'error'|'interrupted')
  created_at, updated_at

user_preferences (PK user_id FK users(id) ON DELETE CASCADE)
  preferences JSONB DEFAULT '{}'
  updated_at
```

Tables are auto-created on first startup via `Base.metadata.create_all`
(`api/app/core/db.py:init_models`). For real production data, migrate to
Alembic before shipping breaking schema changes.

## Roles & permissions

| Resource / action | root | admin | user |
|---|---|---|---|
| Login / change own password | ✅ | ✅ | ✅ |
| Create chat sessions | ✅ | ✅ | ✅ |
| See / edit own sessions | ✅ | ✅ | ✅ |
| Read/write system settings | ✅ | ✅ | ❌ |
| List users | ✅ | ❌ | ❌ |
| Create admin / user | ✅ (via `POST /api/auth/users`) | ❌ | ❌ |
| Edit any user's preferences | ✅ | ❌ | ❌ |
| Delete a user | ✅ (cannot delete self; cannot delete last root) | ❌ | ❌ |
| `create-root` CLI (one-time bootstrap) | n/a (run on the server) | ❌ | ❌ |

`MAX_ROOT_USERS` (default `4`) caps the number of root accounts.
CLI and API both enforce this.

## Agent modes

Each request resolves an **effective mode** using this priority:

1. Request body `mode` field (if provided by the client)
2. `user_preferences.default_mode` (server-side, persisted per user)
3. `simple` (fallback)

When the effective mode is set, the backend injects an extra system
message built from `prompts.yml`:

- `simple` — no extra system prompt
- `knowledge` — prefix + suffix wrapping any RAG chunks (currently the
  `rag.retrieve()` hook returns `[]`, so the prompt is essentially a no-op
  until a RAG source is wired up)
- `think` — Chinese CoT instruction + `max_tokens=4096`

`<think>...</think>` blocks emitted by the model are stripped from the
SSE chunks **and** from the persisted `assistant_content`, so reloads
don't show them either.

## API surface

All endpoints are under `/api`.

### Auth

| Method | Path | Auth | Notes |
|---|---|---|---|
| `POST` | `/api/auth/login` | public | body `{username, password}`; sets cookie |
| `POST` | `/api/auth/logout` | login | clears cookie |
| `GET` | `/api/auth/status` | public | returns `{authenticated, user}` |
| `GET` | `/api/auth/me` | login | includes `preferences` |
| `GET` | `/api/auth/me/preferences` | login | returns effective prefs (defaults merged) |
| `PATCH` | `/api/auth/me/preferences` | login | body `{preferences, replace_all?}` |
| `GET` | `/api/auth/users` | root | list users |
| `POST` | `/api/auth/users` | root | create admin/user |
| `DELETE` | `/api/auth/users/{id}` | root | cannot delete self / last root |
| `PATCH` | `/api/auth/users/{id}/password` | self or root | change password |
| `GET` | `/api/auth/users/{id}/preferences` | root |  |
| `PATCH` | `/api/auth/users/{id}/preferences` | root |  |

### Chat

| Method | Path | Auth | Notes |
|---|---|---|---|
| `GET` | `/api/health` | public | liveness |
| `GET` | `/api/chat/models` | login | UI picker |
| `GET` | `/api/chat/connectivity` | login | pre-flight probe (`?model=...`) |
| `POST` | `/api/chat/sessions` | login | create session, `owner_id = current_user` |
| `GET` | `/api/chat/sessions` | login | list own sessions |
| `GET` | `/api/chat/sessions/{id}` | login | owner only |
| `DELETE` | `/api/chat/sessions/{id}` | login | owner only |
| `GET` | `/api/chat/sessions/{id}/messages` | login | list turns |
| `POST` | `/api/chat/sessions/{id}/messages` | login | **SSE**; body `{content, model?, mode?}` |

### SSE event format

```text
data: {"delta": "你好", "finish_reason": null, "error": null, "tokens_in": 184, "tokens_out": 0}

data: {"delta": "", "finish_reason": "stop", "error": null, "tokens_in": 184, "tokens_out": 1612}
```

## Local quickstart

### Prerequisites

- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- `pnpm` + Node 22+
- PostgreSQL 16+ reachable

### Backend

```bash
cd api
cp .env.example .env
# Edit .env: set LLM_API_KEY

uv sync

# Create the first root user (one-time)
uv run python -m app.cli create-root --username root --password '<password>'

# Run dev server
uv run uvicorn app.main:app --reload --port 8000
```

Tables are auto-created on first startup. Verify:

```bash
curl http://localhost:8000/api/health   # {"status":"ok"}
```

### Frontend

```bash
cd web
pnpm install
pnpm dev
```

Open http://localhost:5173 and sign in as the root user you just created.

## Prompt authoring

All user-facing prompts are in `api/app/core/prompts.yml`:

```yaml
modes:
  think: |
    请先分步骤分析问题，再给出最终结论。
  knowledge:
    prefix: |
      以下是检索到的相关上下文（若无内容请忽略此段）：
    suffix: |
      请基于以上上下文与你的知识回答用户问题。
titles:
  generate: |
    为以下用户消息生成一个简洁的会话标题...
errors:
  openai_unconfigured: "API key not configured for {provider}"
```

Loaded at startup via `app.core.prompts.get_prompts()` / `get("dotted.path")`
/ `render("name", **kwargs)`. Set `PROMPTS_RELOAD=true` to re-read on every
access (useful while iterating).

## Config reference

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `development` | Environment name |
| `API_HOST` / `API_PORT` | `0.0.0.0` / `8000` | Backend bind |
| `WEB_BASE_URL` | `http://localhost:5173` | CORS allow-list (frontend origin) |
| `DATABASE_URL` | _(unset)_ | **Override**. Railway / PaaS inject this. Auto-normalized to `postgresql+asyncpg://…` |
| `POSTGRES_*` | localhost / 5433 / chatapp / postgres / postgreswsl | Fallback when `DATABASE_URL` is unset |
| `LLM_API_BASE` | `https://api.minimax.chat/v1` | Primary endpoint |
| `LLM_API_KEY` | _(empty)_ | Required for streaming to work |
| `LLM_MODEL` | `MiniMax-M3` | Default model |
| `OPENAI_*` / `ANTHROPIC_*` / `OLLAMA_*` | _(empty)_ | Optional alt providers |
| `MAX_ROOT_USERS` | `4` | Cap on `root` accounts (CLI + API both enforce) |
| `SESSION_TTL_SECONDS` | `604800` | Cookie lifetime |
| `SESSION_COOKIE_SECURE` | `false` | Set `true` in production (HTTPS) |
| `SESSION_SECRET` | _(unset)_ | Reserved for signed tokens |
| `PROMPTS_FILE` | `app/core/prompts.yml` | Override prompt source |
| `PROMPTS_RELOAD` | `false` | Hot-reload prompts |

## Deployment (Railway)

Each subdirectory (`api/`, `web/`) has a self-contained `Dockerfile` and
`railway.toml`. Recommended topology: **one Railway project with three
services** (postgres + api + web).

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
     | `WEB_BASE_URL` | _fill after web deploys_ (see step 5) |
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

   The Dockerfile bakes `VITE_API_BASE_URL` in at build time. If the
   variable changes, push again and the service rebuilds.

5. **Backfill `WEB_BASE_URL`**
   - Copy the web service's public URL (e.g., `https://chatapp-pg-web.up.railway.app`)
   - Set it on the API service. It restarts automatically.

6. **Create the first root user**
   - Open the API service → Shell tab
   - Run:
     ```bash
     uv run python -m app.cli create-root --username root --password '<password>'
     ```

7. **Open the web URL and sign in as root**
   - Use **Admin → Users** to create additional admin / user accounts.

### How cross-service calls work

The web SPA talks to the API directly over HTTPS, using
`VITE_API_BASE_URL` as the base. The browser sends the `chatapp_session`
cookie; CORS on the API side allows the web origin (via `WEB_BASE_URL`).
There is no internal proxying — both services are reachable from the
public internet.

## Common tasks

| Task | Command |
|---|---|
| Reset DB (drop everything) | `PGPASSWORD=… psql -h … -c "DROP DATABASE chatapp; CREATE DATABASE chatapp;"` then restart `api` |
| Add another root user (up to `MAX_ROOT_USERS`) | shell into `api` service, run `uv run python -m app.cli create-root --username …` |
| Promote user → admin | root user → `/admin/users` → re-create with `role: admin` (no in-place promote yet) |
| Edit a prompt live | edit `api/app/core/prompts.yml`; with `PROMPTS_RELOAD=true` no restart needed, otherwise redeploy `api` |
| Stream JSON inspection | `curl -N -b cookies.txt http://localhost:8000/api/chat/sessions/{id}/messages -d '{"content":"hi"}' -H 'Content-Type: application/json'` |

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