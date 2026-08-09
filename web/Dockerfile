# syntax=docker/dockerfile:1.6
FROM node:22-alpine AS base

# pnpm via corepack for reproducible installs.
ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH

RUN corepack enable && corepack prepare pnpm@9.15.0 --activate

WORKDIR /app

# ----- dependency layer (cached) -----
FROM base AS deps
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile

# ----- build layer -----
FROM deps AS build
COPY tsconfig.app.json tsconfig.node.json vite.config.ts eslint.config.js ./
COPY index.html ./
COPY src ./src

# Vite reads VITE_API_BASE_URL at build time; default to /api for local dev.
ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}
RUN pnpm build

# ----- runtime layer -----
FROM base AS runtime
WORKDIR /app

# Reuse production-only deps so `serve` is available.
COPY package.json pnpm-lock.yaml* ./
RUN pnpm install --prod --frozen-lockfile \
    && pnpm add -g serve@14

COPY --from=build /app/dist ./dist

# Drop privileges.
RUN addgroup -S appuser 2>/dev/null || true \
    && adduser -S appuser -G appuser 2>/dev/null || true
USER appuser

EXPOSE 3000
ENV PORT=3000

CMD ["sh", "-c", "serve -s dist -l ${PORT}"]