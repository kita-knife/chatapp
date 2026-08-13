# ChatApp-PG

Self-hosted AI platform: chat sessions with multi-provider LLM streaming,
tool-calling against a `library_coderag` Postgres schema, three agent
modes (`simple` / `knowledge` / `think`), per-user preferences, and
per-session turn rows in Postgres.

Built for a single-tenant self-hosted deployment with Dockerfiles for
[Railway](https://railway.app), but runs anywhere that has Python 3.12+ and
Node 22+.

---

## Features

- **Chat sessions** with SSE streaming; each turn is one row
  (`user_content` + `assistant_content` + status + token counts).
- **Multi-provider LLM** routed by model prefix (OpenAI-compatible
  endpoints out of the box, plus Anthropic / Ollama hooks).
- **Three agent modes** (each its own `Agent` instance):
  - `simple` — direct LLM call, no tools
  - `knowledge` — all 6 graph tools + RAG-style system prompt
  - `think` — CoT prompt + higher `max_tokens=4096`
- **Tool calling** against `library_coderag` (`graph_documents`,
  `graph_folders`, `graph_contain_edges`, `graph_invoke_edges`):
  `execute_sql`, `get_db_schema`, `graphdb_retrievedby_keywords`,
  `graphdb_retrieve_relationships`, `project_whole_index_retriever`,
  `project_partial_index_retriever`. Tool calls and results stream to
  the UI as SSE events and render as collapsible blocks in `ChatTurn`.
- **Per-user preferences** persisted in `user_preferences` (JSONB blob) and
  merged on every request (`default_mode`, `default_model`,
  `default_project`, `ui_language`).
- **Title auto-generation**: immediate fallback (truncated user message)
  on first turn + background LLM refinement after the stream finishes.
- **Externalized prompts**: all user-facing prompts live in
  `api/app/core/prompts.yml`; no prompt is hard-coded in code.
- **YAML config** (`api/config.yml`) — single source of truth; falls back to
  `config.example.yml` shape. Override path via `CONFIG_PATH`. PaaS env
  var `DATABASE_URL` takes priority over the YAML's database block.
- **Auth + RBAC**: cookie-session login, three roles (`root` / `admin` /
  `user`), role-scoped endpoints, root can create additional admins/users.
- **Thinking-block filter**: server-side `<think>...</think>` is
  stripped from both the stream and the persisted content (MiniMax-M3
  emits it by default).

## Stack

| Layer | Tech |
|---|---|
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2 (async), `uv` package manager |
| LLM abstraction | [agno](https://github.com/agno-agi/agno) `Agent` + `Model` — provider factory, streaming, tool-call loop, token accounting |
| Config | YAML (`PyYAML` + `pydantic-settings`) — see [`api/config.example.yml`](api/config.example.yml) |
| Frontend | Vite 6, React 18, TypeScript, TanStack Query, React Router 7 |
| Database | PostgreSQL 16+ (uses `pgvector` later) |
| SSE | FastAPI `StreamingResponse` with `text/event-stream` |
| Deploy | Multi-stage Dockerfile per service; `railway.toml` per service |

## Project layout

```
chatapp-pg/
├── api/
│   ├── app/
│   │   ├── core/                  # YAML config loader, db, security, prompts.yml, prompts.py
│   │   ├── api/router.py          # /api/* mount
│   │   ├── cli/                   # `python -m app.cli` (create-root)
│   │   └── modules/
│   │       ├── auth/             # users, auth_sessions, login/me/logout
│   │       │   └── users/         # root-only user CRUD
│   │       ├── chat/             # sessions, messages (turns), providers
│   │       │   ├── agents/        # simple / knowledge / think Agent factories
│   │       │   ├── tools/        # 6 library_coderag tools (@tool-decorated)
│   │       │   └── utils.py      # check_and_truncate_output
│   │       └── users_prefs/      # preferences table + endpoints
│   ├── config.example.yml         # template — copy to config.yml
│   ├── Dockerfile                # Python 3.12-slim + uv + libpq
│   ├── railway.toml              # Railway service config
│   └── pyproject.toml
├── web/
│   ├── src/
│   │   ├── api/client.ts          # fetch wrapper, all API methods
│   │   ├── app/                   # router, AppShell
│   │   ├── auth/                  # login page, useAuth hook
│   │   ├── chat/                  # ChatPage (4-dropdowns: lang/mode/model/project)
│   │   ├── rag/ mcp/ settings/    # placeholder pages (future; Settings is reserved)
│   │   ├── admin/                 # AdminUsersPage (root only)
│   │   ├── components/            # ChatInput, ChatTurn (renders tool trace), SessionList
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

`user_preferences.preferences` is a JSONB blob with these keys (all
optional; defaults are filled in by `users_prefs.service.get_preferences`):

| Key | Default | Meaning |
|---|---|---|
| `default_mode` | `"simple"` | `simple` \| `knowledge` \| `think` |
| `default_model` | _(None)_ | Resolved to `settings.openlike_model` at read time |
| `default_project` | `""` | Library_coderag project name; empty disables Send |
| `ui_language` | `"zh"` | `"zh"` \| `"en"` |
| `system_prompt_overrides` | `{think: None, knowledge: None}` | Per-mode prompt overrides |

Schema is managed by Alembic under `api/migrations/`. All tables (plus
`alembic_version`) live in the **`ai` PostgreSQL schema**, not `public`.
Run `alembic upgrade head` from `api/` before the first start, and again
on every deploy (the Dockerfile and Railway `releaseCommand` both do this
automatically).

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

Each mode maps to a distinct `Agent` instance built from
[`api/app/modules/chat/agents/`](api/app/modules/chat/agents):

| Mode | Agent file | Tools | `max_tokens` | Notes |
|---|---|---|---|---|
| `simple` | `simple.py` | none | default | Direct chat, no project hint |
| `knowledge` | `knowledge.py` | all 6 graph tools | default | RAG-style prompt prefix/suffix from `prompts.yml` |
| `think` | `think.py` | all 6 graph tools | `4096` | CoT prompt + larger token budget |

The active project name (from `user_preferences.default_project`) is
injected into the knowledge / think agent's instructions so the LLM
knows what to pass to tools that have a `project` parameter (notably
`project_whole_index_retriever`, whose cache key includes `project`).

`<think>...</think>` blocks emitted by the model are stripped from the
SSE chunks **and** from the persisted `assistant_content`, so reloads
don't show them either.

### Tool calling

When the user has selected a project and the active mode is
`knowledge` / `think`, the model can call any of the six tools in
[`api/app/modules/chat/tools/`](api/app/modules/chat/tools). All tools
read their project binding from `RunContext.session_state["project"]`
which the agent populates from the current request — except
`project_whole_index_retriever`, which expects the LLM to pass
`project` as a function argument so its result cache is keyed per
project. The active project is also surfaced via instructions so the
LLM knows the value.

Each tool emits two SSE events back to the UI: `tool_call` (the call
the model is making) and `tool_result` (the response). `ChatTurn`
renders them as a collapsible `🔧 N tool calls` block above the
assistant reply.

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
| `GET` | `/api/chat/projects` | login | distinct project names from `library_coderag.graph_folders` (populates the project dropdown) |
| `GET` | `/api/chat/connectivity` | login | pre-flight probe (`?model=...`) |
| `POST` | `/api/chat/sessions` | login | create session, `owner_id = current_user` |
| `GET` | `/api/chat/sessions` | login | list own sessions |
| `GET` | `/api/chat/sessions/{id}` | login | owner only |
| `DELETE` | `/api/chat/sessions/{id}` | login | owner only |
| `GET` | `/api/chat/sessions/{id}/messages` | login | list turns |
| `POST` | `/api/chat/sessions/{id}/messages` | login | **SSE**; body `{content, model?, mode?, project?}` |

### SSE event format

Each `data:` line is a JSON object. Field combinations by phase:

```text
# Content streamed
data: {"delta": "你好", "finish_reason": null, "error": null, "tokens_in": 184, "tokens_out": 0, "tool_call": null, "tool_result": null}

# Tool call (model decides to call a tool)
data: {"delta": "", "tool_call": {"id": "call_xyz", "name": "execute_sql", "arguments": {"sql": "SELECT ..."}}, "tool_result": null}

# Tool result (after tool execution)
data: {"delta": "", "tool_call": null, "tool_result": {"tool_call_id": "call_xyz", "name": "execute_sql", "result": "[{...}]"}}

# Final
data: {"delta": "", "finish_reason": "stop", "tokens_in": 184, "tokens_out": 1612, "tool_call": null, "tool_result": null}
```

The `tool_call` and `tool_result` events drive the collapsible
`🔧 N tool calls` block in `ChatTurn`. Streaming chunks with
`finish_reason="error"` carry an `error` string instead of `delta`.

## Bootstrap from scratch

This walks through every step needed to take a clean machine to a logged-in
chat session — Postgres, alembic migrations, root user, backend, and
frontend.

### 0. Prerequisites

| Tool | Min version | Why |
|---|---|---|
| PostgreSQL | 16+ | backend storage (we use `ai` schema, not `public`) |
| Python | 3.12+ | backend runtime |
| [`uv`](https://docs.astral.sh/uv/) | latest | Python package manager (reads `pyproject.toml` + `uv.lock`) |
| Node.js | 22+ | frontend toolchain |
| pnpm | 9+ | JS package manager |

> Make sure `psql` is on `$PATH` — you'll use it once to create the
> database.

### 1. Create the database

Pick a name (we use `chatapp` throughout the docs) and a superuser / role
that can `CREATE` / DDL.

```bash
# Local Postgres (defaults match config.example.yml):
PGPASSWORD=postgreswsl psql -h localhost -p 5433 -U postgres \
  -c "CREATE DATABASE chatapp;"

# Or with DATABASE_URL injection:
psql "postgresql://user:pass@host:5432/postgres" -c "CREATE DATABASE chatapp;"
```

You only do this **once per database**. Tables, indexes, and the `ai`
schema are created by the migration in step 3.

### 2. Configure the backend

```bash
cd api
cp config.example.yml config.yml
```

Edit `config.yml`. The three things that must be set before anything works:

```yaml
app:
  web_base_url: http://localhost:5173   # CORS allow-list (must match the URL the browser opens)

llm:
  openlike:
    api_base: https://api.minimax.chat/v1
    api_key: sk-...

# Database is auto-resolved from the `database.postgres.*` defaults in
# config.example.yml. Override here only if your Postgres is elsewhere:
# database:
#   url: postgresql+asyncpg://user:pass@host:5432/chatapp

# Graph DB schema for tool calling (library_coderag):
graph:
  schema: library_coderag
  default_project: ""   # optional: fallback if user hasn't picked one
```

Railway / Heroku / PaaS deployments inject `DATABASE_URL` via the shell
environment; that value takes priority over the YAML's `database.url` and
`database.postgres.*` blocks.

Then install Python dependencies (creates `.venv/`):

```bash
uv sync
```

### 3. Apply database migrations

This creates the `ai` schema + all 5 tables + the `ai.alembic_version`
table. `env.py` pre-creates the schema for you, so this works on a
brand-new empty database with no manual `CREATE SCHEMA` step.

```bash
uv run alembic upgrade head
# INFO  [alembic.runtime.migration] Running upgrade  -> 0001_initial_schema, initial schema
```

Verify in psql:

```bash
PGPASSWORD=postgreswsl psql -h localhost -p 5433 -U postgres -d chatapp \
  -c "\dt ai.*"
#  alembic_version  | auth_sessions  | chat_messages
#  chat_sessions    | user_preferences | users
```

### 4. Create the first root user

The web app has **no self-signup flow** — root must exist before anyone
can log in. Skip this and login fails with "invalid credentials" no
matter what you type.

```bash
uv run python -m app.cli create-root \
  --username root \
  --password '<choose-a-real-one>'
# ✓ root user 'root' created (1/4)
```

The `(1/4)` is current/total — `MAX_ROOT_USERS` (default `4`) caps how many
root accounts can exist.

### 5. Start the backend

```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# INFO:     Application startup complete.
# INFO:     Uvicorn running on http://0.0.0.0:8000
```

Health check (open a second terminal):

```bash
curl http://localhost:8000/api/health
# {"status":"ok"}
```

### 6. Start the frontend

```bash
cd ../web
pnpm install     # first time only — reads pnpm-lock.yaml
pnpm dev         # http://localhost:5173
```

The Vite dev server proxies `/api/*` to `http://localhost:8000`, so no
extra configuration is needed for local dev.

### 7. Log in

Open http://localhost:5173 and sign in with the root credentials from step 4.
You should land on the chat page with a health pill showing `LLM ✓` (the
frontend pings `/api/chat/connectivity` against your default model).

### 8. Add more users

Once logged in as root, **Admin → Users** lets you create additional
`admin` / `user` accounts through the UI (max `MAX_ROOT_USERS` root
accounts via `create-root` CLI on the server).

---

### Recap: the minimal first-time sequence

```bash
# 1. Create DB (once per machine)
PGPASSWORD=postgreswsl psql -h localhost -p 5433 -U postgres \
  -c "CREATE DATABASE chatapp;"

# 2. Backend
cd api
cp config.example.yml config.yml   # then edit llm.openlike.api_key, web_base_url
uv sync
uv run alembic upgrade head        # creates ai schema + 5 tables
uv run python -m app.cli create-root --username root --password 'YOUR_PW'
uv run uvicorn app.main:app --reload --port 8000

# 3. Frontend (separate terminal)
cd ../web
pnpm install
pnpm dev                        # http://localhost:5173
```

### Production build (web)

```bash
cd web
VITE_API_BASE_URL=https://api.your-domain.example.com pnpm build
# dist/  ← serve with nginx / Caddy / Cloudflare Pages / `serve -s dist -l 3000`
```

`VITE_API_BASE_URL` is baked into the JS bundle at build time — rebuild
whenever the API URL changes.

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

Configuration is read from `api/config.yml` (template at
[`api/config.example.yml`](api/config.example.yml)). The file is required —
the process exits at startup if it is missing. Override the path with
`CONFIG_PATH=/path/to/config.yml` (used by Railway volume mounts).

Only `DATABASE_URL` is also read from the shell environment (Railway /
Heroku / PaaS inject it on linked services); when set, it wins over the
YAML `database.url` and `database.postgres.*` blocks.

The full YAML schema (every field with its default and meaning) is at
[`api/config.example.yml`](api/config.example.yml).

### Graph DB (`library_coderag`)

The `graph` block configures the schema used by tool-calling agents:

```yaml
graph:
  schema: library_coderag   # Postgres schema containing the graph tables
  default_project: ""       # fallback if user hasn't picked one in the UI
```

The schema must contain the four graph tables: `graph_folders`,
`graph_documents`, `graph_contain_edges`, `graph_invoke_edges`. Tools
read the active project name from `RunContext.session_state["project"]`
(except `project_whole_index_retriever`, which expects it as a function
argument so its cache key is per-project).

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
   - Provide `config.yml` to the container. Two options:
     - **Volume mount**: Settings → Volumes → Mount a file at `/app/config.yml`,
       or use a **Config Variable** and pipe it through an entrypoint wrapper.
     - **Bake into the image** (only if you're OK rebuilding on every
       change): add a `COPY config.yml ./config.yml` step above the
       uvicorn `CMD` in `api/Dockerfile`.
   - **Environment variables** (only `DATABASE_URL` is read from the shell;
     everything else lives in `config.yml`):

     | Key | Value |
     |---|---|
     | `DATABASE_URL` | `{{ postgres.DATABASE_URL }}` |

    - In `config.yml` set, at minimum:

      ```yaml
      app:
        web_base_url: https://chatapp-pg-web.up.railway.app   # backfill after step 5
      llm:
        openlike:
          api_base: https://api.minimax.chat/v1
          api_key: sk-...
          model: MiniMax-M3
      auth:
        max_root_users: 4
        session:
          cookie_secure: true   # production over HTTPS
      graph:
        schema: library_coderag
      ```

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
| Reset DB (drop everything) | `PGPASSWORD=… psql -h … -c "DROP DATABASE chatapp; CREATE DATABASE chatapp;"` then `uv run alembic upgrade head` and `create-root` |
| Add another root user (up to `MAX_ROOT_USERS`) | shell into `api` service, run `uv run python -m app.cli create-root --username …` |
| Promote user → admin | root user → `/admin/users` → re-create with `role: admin` (no in-place promote yet) |
| Edit a prompt live | edit `api/app/core/prompts.yml`; with `PROMPTS_RELOAD=true` no restart needed, otherwise redeploy `api` |
| Pick a project for tool calling | UI → ChatInput → project dropdown (top-right). Persisted in `user_preferences.default_project`. |
| Stream JSON inspection (with tool events) | `curl -N -b cookies.txt http://localhost:8000/api/chat/sessions/{id}/messages -d '{"content":"hi","project":"LICSXP_VER11.0"}' -H 'Content-Type: application/json'` |
| List available projects | `curl -b cookies.txt http://localhost:8000/api/chat/projects` |

## Troubleshooting

**"I just deployed and login fails with invalid credentials."**

You almost certainly skipped step 2 above — the web app does not have a
self-signup flow. Run `create-root` once on the server (or in your local
terminal) and try again. Then use **Admin → Users** to create additional
non-root accounts.

**"First login click doesn't navigate, only the second one does."**

Fixed in the latest code (see `useAuth.ts → useLogin.onSuccess`). Make sure
your web bundle includes the fix (rebuild the web service / repull the
image). If the symptom reappears, check that no stale build is being served.

**"I get `alembic_version` does not exist" or other migration errors."**

The DB was created by the previous auto-create-all path. Run `uv run alembic
stamp head` to mark it as up-to-date without re-running DDL, then continue
normal `alembic upgrade head` from then on.

**"Tools don't run — model just responds with text."**

Make sure the user has selected a project in the ChatInput dropdown (top-right,
next to the mode dropdown). Without a project, the Send button is disabled
and tools can't bind `:project`. Also check that `graph.schema` in
`config.yml` points to a schema containing the four graph tables.

**"Tool results look like they're from the wrong project."**

`project_whole_index_retriever` caches results per `(project, format)` pair.
If the LLM doesn't pass `project` in its tool call, the cache key collapses
to `project=""` and may return stale results. The agent's instructions
include "Current project: 'X'. When calling project_whole_index_retriever,
always pass project='X'" — if the model ignores this, the cache may be
polluted. Clear the cache by restarting the API process.

## Iteration roadmap

| # | Content | Status |
|---|---|---|
| 1 | Backend + Web skeleton, multi-provider LLM, SSE, Postgres for chat history | ✅ |
| 2 | Auth (session cookie + `create-root` CLI + role-based access) | ✅ |
| 3 | Per-user preferences (`user_preferences` JSONB), settings page (reserved, empty) | ✅ |
| 4 | Agent modes (simple / knowledge / think) as separate Agent instances | ✅ |
| 5 | Tool calling against `library_coderag` (6 graph tools, project-aware, SSE tool events) | ✅ |
| 6 | YAML config (`config.yml`) with `DATABASE_URL` env override | ✅ |
| 7 | RAG (Git/Local + pgvector) | pending |
| 8 | MCP Client + default GitHub / Filesystem / Fetch | pending |
| 9 | Sandbox (Docker SDK isolation) | pending |
| 10 | Background workers (Redis + Arq) | pending |
| 6 | MCP Client + default GitHub / Filesystem / Fetch | pending |
| 7 | Sandbox (Docker SDK isolation) | pending |
| 8 | Background workers (Redis + Arq) | pending |