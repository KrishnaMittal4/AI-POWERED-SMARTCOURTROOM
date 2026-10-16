# LEXAI — Supabase + Render Free deployment

Production keeps the 848-judgment research corpus disabled. Supabase stores only deployed users, private cases, private PDFs and derived case intelligence.

## 1. Supabase database
Open **SQL Editor** and run `supabase/schema.sql` once. It is idempotent and can also upgrade the earlier LEXAI schema by adding the authentication/cache fields needed by this build.

## 2. Storage
Keep the existing bucket named `lexai-private` **Private**. Do not add a public-read policy.

## 3. Render secrets
`render.yaml` supplies non-secret production flags. In Render add these secret values manually:

- `SUPABASE_SERVICE_ROLE_KEY` — Supabase backend Secret/service-role key (never the publishable key)
- `GROQ_API_KEY` and/or `GEMINI_API_KEY`
- `AUTH_SECRET` — long random value; changing it invalidates sessions
- `CORS_ORIGINS` — your Vercel URL, e.g. `https://your-app.vercel.app`
- `ADMIN_API_KEY` if admin endpoints are used

Do not put the Supabase server secret, Groq key or Gemini key in frontend `.env`, any `VITE_*` variable, GitHub, screenshots, or client JavaScript.

## 4. Production data flow
`Browser -> LEXAI FastAPI JWT/ownership check -> Supabase PostgreSQL/Storage`.
The browser never receives the Supabase server secret.

Private PDFs are stored under:
`users/<supabase-user-uuid>/cases/<case-uuid>/documents/<document-uuid>/<filename>`

## 5. Local development
Leave `LEXAI_STORAGE_BACKEND=local`. Existing SQLite/local-file behavior remains available, including the optional research corpus/RAG Lab when their development flags are enabled.

## 6. Render Free behavior
- global 848-judgment corpus: disabled
- developer/RAG Lab: disabled
- Cross-Encoder: disabled in low-memory mode
- MiniLM: lazy-loaded for private semantic retrieval
- PDFs/case metadata: persistent in Supabase
- private FAISS/BM25 index: disposable cache and rebuilt from persistent PDFs when Render restarts

This separation means a Render restart can discard local cache files without losing the user's private case source documents or saved Case Intelligence.
