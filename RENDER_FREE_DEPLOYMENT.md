# LEXAI - Render Free deployment

This profile is intended for a college/demo deployment with limited RAM and ephemeral storage.

## What is disabled
- 848-judgment research corpus and its FAISS/BM25 indexes
- RAG Lab / developer tools
- Resident Cross-Encoder reranker

## What remains enabled
- Private Case PDF upload and OCR
- Per-user/per-case private FAISS + BM25 hybrid retrieval
- Lazy MiniLM loading on first private RAG use
- Case Intelligence, evidence, timeline, contradictions, Issue Map, Moot Court
- Groq + Gemini task-aware routing/fallback

## Render setup
Use the included `render.yaml`, or configure a Python Web Service with:

Build command:
`pip install --no-cache-dir -r requirements.txt`

Start command:
`uvicorn main:app --host 0.0.0.0 --port $PORT`

Health check:
`/health`

Set secrets in the Render dashboard (never commit them):
- `GROQ_API_KEY`
- `GEMINI_API_KEY`
- `ADMIN_API_KEY`
- `CORS_ORIGINS=https://YOUR-VERCEL-APP.vercel.app`

At least one of GROQ_API_KEY or GEMINI_API_KEY is required.

## Important storage limitation
Render Free storage is ephemeral. Uploaded private cases are demo/session data and may disappear after restart/redeploy/spin-down. Do not promise persistence to users on this profile. For persistent production data, move files/DB/indexes to external storage or a paid persistent disk.

## Frontend
Deploy `frontend/` to Vercel (Root Directory: `frontend`) and set environment variable:
`VITE_API_BASE=https://YOUR-RENDER-SERVICE.onrender.com`
*(Note: `VITE_API_URL` is also supported as a fallback)*

