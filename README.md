# kelsa.ai

AI Internship and Career Advisor built with FastAPI and a single-page frontend.

## Run locally

```bash
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m uvicorn main:app --reload
```

Open `http://127.0.0.1:8090`.

## Notes

- The app now works without Hindsight by using a local JSON-backed fallback store.
- To enable Hindsight explicitly, set `HINDSIGHT_ENABLED=true` and provide the relevant env vars.
- Local fallback data is written to `memory_store.json`.
