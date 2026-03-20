# Deployment Guide

This document covers a practical path to deploy `kelsa.ai` beyond local development.

## Recommended baseline

- run the FastAPI app behind Nginx or Caddy
- enable HTTPS
- set a real `SESSION_SECRET`
- disable reload mode
- keep the app on a private internal port

## Environment

Example production-style environment values:

```env
SESSION_SECRET=use-a-long-random-secret-here
APP_HOST=0.0.0.0
APP_PORT=8090
APP_RELOAD=false
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_SAMESITE=lax
SESSION_COOKIE_MAX_AGE=604800

HINDSIGHT_ENABLED=false
HINDSIGHT_BASE_URL=https://api.hindsight.vectorize.io
HINDSIGHT_API_KEY=
```

## Start command

```bash
.venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8090
```

If you set `APP_HOST`, `APP_PORT`, and `APP_RELOAD` in the environment, running `python main.py` will also use those values.

## Reverse proxy

Recommended reverse-proxy behavior:

- terminate TLS at the proxy
- forward traffic to the app on `127.0.0.1:8090`
- preserve standard forwarded headers

## Data persistence

The current implementation uses:

- `users.json`
- `memory_store.json`

This is fine for demos and small deployments, but it is not ideal for:

- high write concurrency
- multiple app replicas
- larger production workloads

For more serious production use, move persistence to a database.

## Cookies and auth

For HTTPS production deployments:

- set `SESSION_COOKIE_SECURE=true`
- set a strong `SESSION_SECRET`
- review whether `SESSION_COOKIE_SAMESITE=lax` fits your final frontend hosting pattern

## Hindsight

If you want Hindsight in production:

- set `HINDSIGHT_ENABLED=true`
- set `HINDSIGHT_BASE_URL`
- set `HINDSIGHT_API_KEY`
- verify network access from the host

## Operational notes

- back up `users.json` and `memory_store.json` if you keep local persistence
- keep `.env` out of Git
- do not run with `--reload` in production
