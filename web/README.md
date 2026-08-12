# ChatApp-PG Web

Vite + React + TypeScript SPA. Talks to the FastAPI backend at `/api/*`.

## Bootstrap

```bash
pnpm install
```

## Dev

```bash
pnpm dev          # http://localhost:5173
```

The Vite dev server proxies `/api/*` to `http://localhost:8000` (the FastAPI
backend), so no extra configuration is needed for local dev.

## Production build

```bash
VITE_API_BASE_URL=https://api.your-domain.example.com pnpm build
```

`VITE_API_BASE_URL` is baked into the JS bundle at build time — rebuild
whenever the API URL changes. The output lands in `dist/` and can be served
from any static host (nginx, Caddy, Cloudflare Pages, `serve -s dist`, …).

## Lint / type-check

```bash
pnpm typecheck    # tsc --noEmit
pnpm lint         # eslint .
pnpm build        # tsc -b && vite build (full build, used in CI / Docker)
```