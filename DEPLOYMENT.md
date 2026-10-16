# LEXAI deployment

## Production design
The 848-judgment corpus is research-only and is not required in production.
Production uses Private Case RAG: per-user/per-case PDFs -> native extraction/OCR -> private case-role metadata -> MiniLM/FAISS + BM25 hybrid retrieval -> Cross-Encoder -> source/page-grounded answer and Case Intelligence.

## Backend (Railway recommended)
1. Push this cleaned repository to GitHub. The root `.gitignore` excludes the research corpus, research indexes, benchmark exports, secrets, and private runtime data.
2. Create a Railway service from the repository. The included Dockerfile/railway.json start FastAPI.
3. Add a persistent volume mounted at `/data`.
4. Set environment variables:
   - `LEXAI_ENV=production`
   - `GLOBAL_JUDGMENT_CORPUS_ENABLED=false`
   - `ENABLE_DEVELOPER_TOOLS=false`
   - `LEXAI_DATA_ROOT=/data/lexai`
   - `AUTH_DB_PATH=/data/lexai/users.db`
   - `CASE_DB_PATH=/data/lexai/cases.db`
   - `CASE_FILES_DIR=/data/lexai/user_case_files`
   - `CASE_INDEX_DIR=/data/lexai/user_case_indexes`
   - `GROQ_API_KEY=...`
   - `GEMINI_API_KEY=...`
   - `AUTH_SECRET=<long random secret>`
   - `ADMIN_API_KEY=<long random secret>`
   - `CORS_ORIGINS=https://<your-vercel-domain>`
5. Do not upload `judgments/`, `index_store/`, benchmark JSON/CSV, or `.env` to the service.
6. `/health` should report `global_judgment_corpus: false`, `private_case_rag: true`, and `developer_tools: false`.

## Frontend (Vercel)
1. Deploy the `frontend` directory as a Vite project.
2. Set `VITE_API_BASE=https://<your-railway-domain>`.
3. Do not add Groq/Gemini keys to Vercel frontend variables.

## Local research mode
Use:
`LEXAI_ENV=development`
`GLOBAL_JUDGMENT_CORPUS_ENABLED=true`
`ENABLE_DEVELOPER_TOOLS=true`

Local research mode can load the 848 judgments and RAG Lab; production mode does not.

## One-pass deployment smoke test
- `/health` returns 200 and production capability flags.
- Sign up/login works.
- Create a Private Case.
- Upload one PDF; restart/redeploy backend and confirm it remains (persistent volume).
- Ask a case question and verify source filename/page appears.
- Run Case Intelligence and Issue Map; with global corpus disabled, private evidence remains available and authority mapping clearly says it is unavailable.
- Moot Court uses Gemini/Groq router without exposing raw provider errors.
