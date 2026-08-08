# ChatApp-PG Web

Vite + React + TypeScript SPA. Talks to the FastAPI backend at `/api/*`.

## Setup

```bash
pnpm install
```

## Run

```bash
pnpm dev
```

Then open http://localhost:5173.

The Vite dev server proxies `/api/*` to `http://localhost:8000` (the FastAPI backend).
