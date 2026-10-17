# Smart Courtroom: Legal RAG with Checked Citations

A research tool over Indian court judgments. Every answer is written **only from
retrieved passages**, then every case it names is checked against the source text.

```
PDFs -> extract/clean -> chunk (180 words, 40 overlap) + metadata header
     -> MiniLM embeddings (FAISS) + BM25 -> RRF fusion -> cross-encoder rerank
     -> Groq LLM answer -> citation verification -> precedent status -> UI
```

## How it works

| Stage | What happens | Files |
|---|---|---|
| Ingest | PyMuPDF (pdfplumber fallback), cleaning, chunking, case/court/case-no/citation metadata prepended to each chunk | `rag_pipeline.py`, `metadata_extraction.py` |
| Retrieve | Query rewrite (LLM) -> dense FAISS + BM25 fused with RRF -> cross-encoder re-rank of top 15 -> max 2 chunks per document | `rag_pipeline.py`, `generate_answer.py` |
| Refuse | If the best dense cosine score is below `MIN_RETRIEVAL_SCORE`, no answer is written (see below) | `generate_answer.py` |
| Answer | `openai/gpt-oss-120b` on Groq, temperature 0.2, strict "only these passages, only these case names" prompt | `generate_answer.py` |
| Verify | Per cited case: exists in corpus, case number matches, passage supports the claim (Groq judge, optional Gemini cross-check; disagreement shows as "disputed"). Citation-shaped text matching no corpus case is flagged | `citation_verification.py` |
| Intelligence | Precedent status badge, ratio/obiter extraction, court-draft templates | `legal_intelligence.py` |
| Similar cases | `POST /similar`: judgments like a passage or a whole judgment, grouped by document (one row per case, ranked by best-matching passage), no LLM call | `similar_cases.py` |
| Moot Court Debate | `POST /moot-court`: Multi-agent adversarial courtroom trial: Petitioner (Groq) vs. Respondent (Groq) vs. Presiding Bench (Gemini) with dual FAISS retrieval & ratio formulation | `moot_court.py` |
| API | FastAPI: `/query`, SSE `/query/stream`, `/feedback`, `/documents`, `/upload`, `/similar`, `/moot-court`, `/precedent/check`, `/analyze/ratio-obiter`, `/draft/*` | `main.py`, `security.py`, `feedback_store.py` |
| UI | React + Vite: streaming answers, citations coloured by verdict, evidence panel, moot court modal, history, sanitized markdown | `frontend/` |

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env          # add GROQ_API_KEY (and optionally GEMINI_API_KEY)
```

**Corpus.** Put judgment PDFs in `judgments/`. Bulk Supreme Court PDFs:
`python download_1000_judgments.py --count 1000 --out judgments` (public AWS dataset,
CC-BY-4.0). Indian Kanoon PDFs can be added by hand. `make_sample_pdfs.py` creates three
synthetic samples for a quick smoke test.

**Index.**
```bash
python rag_pipeline.py        # builds index_store/ (FAISS + records + BM25)
python index_report.py        # writes index_report.json + index_manifest.csv
```

**Run.**
```bash
uvicorn main:app --reload --port 8000        # backend, docs at /docs
cd frontend && npm install && npm run dev    # UI at http://localhost:5173
```
The UI reads `VITE_API_BASE` (see `frontend/.env.example`) and falls back to
`http://localhost:8000`.

## When the corpus does not cover a question

Retrieval is gated on the cosine score of the best chunk:

- below `MIN_RETRIEVAL_SCORE` (default **0.54**) -> no grounded answer; the UI shows
  "Not covered by these judgments" and the closest passages.
- below `WEAK_RETRIEVAL_SCORE` (default 0.55) -> answered, but flagged as a weak match.

Dense score alone does not fully separate answerable from unanswerable queries on this
corpus (the eval calibration reports `separable: false`: lowest answerable top score
0.552, highest unanswerable 0.597). Two optional safeguards:

- `RERANK_MIN_SCORE` (+ `RERANK_GATE_BELOW`, default 0.62): inside the ambiguous band,
  also require the cross-encoder's top score to reach this value. Off by default; the
  scores are raw logits, so calibrate on your own eval set before enabling.
- `ALLOW_STATUTORY_FALLBACK=1`: lets the model write a general-law overview from its own
  knowledge when nothing matches. **Off by default.** That text is not grounded in the
  corpus and its citations are not verified, so it is always prefixed with a disclaimer
  and shown in a separate, labelled card.

## Precedent status

The badge on each cited case is **not** a verified citator result unless marked so:

- `verified` + `curated`: matches the hand-checked `KNOWN_OVERRULED_CASES` table.
- `ai_estimate`: a language model judged from the case name alone. Treat it as a prompt
  to check a citator.
- `unknown` (grey, "Status unverified"): not recognised, or the check failed. The tool
  never defaults to "good law".

## Evaluation

```bash
python eval_pipeline.py          # retrieval metrics + threshold calibration (no LLM calls)
python eval_pipeline.py --full   # + citation accuracy (uses Groq)
```
Latest run (`eval_after_metadata.json`; 38 queries, 31 answerable, 7 unanswerable):
Precision@3 0.559, MRR 0.839, hit@3 0.839. At threshold 0.54, 6 of 7 unanswerable queries
are refused and 0 answerable ones are wrongly refused. The earlier 8-query A/B
(`minilm_baseline.json` vs `inlegalbert_baseline.json`) is why `all-MiniLM-L6-v2` is the
embedding model (P@3 0.571 vs 0.286). The eval set is small, so treat these as indicative.

## Deployment (Render backend + Vercel frontend)

`render.yaml` deploys the backend on Render's free tier (512 MB RAM) using the small
committed index `index_store_backup_20261005_152032` (7,362 chunks). The full index
(~52k chunks, 848 documents) needs a paid plan and a persistent disk; set `INDEX_DIR`.
Set `GROQ_API_KEY`, `ADMIN_API_KEY` and `CORS_ORIGINS` (your exact Vercel domain) in the
Render dashboard. Deploy the frontend to Vercel with `VITE_API_BASE` set to the Render URL.

## Configuration reference

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | required | LLM calls |
| `GEMINI_API_KEY` | unset | optional second citation verifier |
| `INDEX_DIR` / `JUDGMENTS_DIR` | `index_store` / `judgments` | index and PDF locations |
| `MIN_RETRIEVAL_SCORE` | 0.54 | refuse below this best-chunk cosine score |
| `WEAK_RETRIEVAL_SCORE` | 0.55 | flag weak matches below this |
| `RERANK_MIN_SCORE`, `RERANK_GATE_BELOW` | unset, 0.62 | optional second refusal gate (see above) |
| `ALLOW_STATUTORY_FALLBACK` | 0 | allow ungrounded general-law overview (disclaimed) |
| `ADMIN_API_KEY` | unset | required `X-Admin-Key` for upload/delete/feedback listing; unset = those routes return 403 |
| `RATE_LIMIT_PER_MIN` / `_PER_DAY` / `_GLOBAL_PER_MIN` | 6 / 100 / 12 | limits on routes that call Groq |
| `TRUST_PROXY_HOPS` | 1 | trusted proxies for `X-Forwarded-For` (Render = 1) |
| `CORS_ORIGINS` | localhost + `*.vercel.app` | when set, only these origins are allowed |
| `MAX_UPLOAD_FILES` / `MAX_UPLOAD_MB` | 20 / 30 | upload caps |

Notes: Groq limits apply per organization, not per key. Rate limits are in memory and
assume one worker process, as in `render.yaml`.

## Maintenance scripts

| Script | Purpose |
|---|---|
| `fix_index_metadata.py` | repair case names/court/case-no and drop duplicate PDFs in an existing index without re-embedding |
| `remove_years.py` | drop a range of Supreme Court bulk years from the index |
| `diagnose_headers.py` | show why SCR header parsing failed on specific PDFs |
| `index_report.py` | corpus health report |

## Known limitations

- Citation verification relies on an LLM judge; "supported" is strong evidence, not proof.
- Scanned (image-only) PDFs have no extractable text and are skipped.
- Precedent status is only verified for the curated table (see above).
- Draft templates produce starting points for an advocate to review, not filings.


## Authentication

Smart Courtroom now includes account-based access. Users can create an account or sign in; passwords are salted and hashed with PBKDF2-HMAC-SHA256, API requests require a signed bearer token, and browser research history is namespaced by user ID so accounts do not share history on the same device.

For production, set `AUTH_SECRET` to a long random value in the backend environment. The default session lifetime is seven days and can be changed with `AUTH_TOKEN_TTL_SECONDS`. User accounts are stored in `users.db` by default; on hosts with ephemeral filesystems, configure `AUTH_DB_PATH` on persistent storage or migrate the auth store to a managed database before production use.

### Private case workspaces
Authenticated users can create isolated case workspaces and upload private PDF evidence/documents. Ownership is enforced server-side on every case/document endpoint. Private files are stored under `user_case_files/<user_id>/<case_id>/` and metadata is kept in `cases.db`; both are ignored by Git. Research history is namespaced by account and case in the browser. The shared legal judgment corpus remains separate from private case evidence.

## Private Case Intelligence (multi-user)
Authenticated case workspaces now reuse the main hybrid retrieval architecture without mixing private evidence into the shared judgment corpus.

- Each user/case has an isolated FAISS + BM25 index under `user_case_indexes/<user>/<case>/`.
- Private PDFs are extracted page-by-page, cleaned, chunked with overlap, embedded with the same MiniLM model, fused with BM25 via RRF, and cross-encoder reranked.
- **Ask Case AI** supports `Case documents`, `Legal judgments`, and `Both` modes.
- Private answers return document/page sources and can run the existing citation verifier.
- Case intelligence tabs generate source-grounded **Timeline**, **Evidence**, and **Contradiction** analyses from private files.
- Uploading/removing a case PDF invalidates only that case index; it is rebuilt lazily on the next private query.

Runtime private indexes are excluded from Git by `.gitignore`.

## Case Workspace V2
Authenticated case workspaces now include a My Cases dashboard, private document management, Case/Global/Both hybrid RAG, timeline/evidence/contradiction analysis, a cited Legal Argument Builder, persistent per-case Research Notebook, automatic neutral Case Brief generation, and a case-aware Moot Court that grounds the simulation in retrieved private evidence plus the shared judgment corpus. Private case indexes and notes remain scoped to the authenticated owner.

## Case Workspace stabilization patch
- Fixed private/global `delete_document` name collision.
- Case query and each expensive case-intelligence operation now have independent rate-limit scopes.
- Timeline, evidence and contradiction analysis no longer sends the whole case to `openai/gpt-oss-120b` in one request. It maps over bounded source pages using `GROQ_ANALYSIS_MODEL` (default `openai/gpt-oss-20b`) and reduces extracted claims for contradiction detection.
- Optional rate-limit env vars: `CASE_QUERY_PER_MIN`, `CASE_QUERY_PER_DAY`, `CASE_ANALYSIS_PER_MIN`, `CASE_ANALYSIS_PER_DAY`, `CASE_ARGUMENT_PER_MIN`, `CASE_ARGUMENT_PER_DAY`, `CASE_BRIEF_PER_MIN`, `CASE_BRIEF_PER_DAY`, `CASE_MOOT_PER_MIN`, `CASE_MOOT_PER_DAY`.

## Verification clarity patch
- Gemini secondary citation verification retries temporary 429/5xx/high-demand failures with short backoff before Groq fallback.
- Groq fallback is explicitly labelled as a resilience fallback, not an independent-provider cross-check.
- Citation/claim support and later precedent treatment are displayed as separate statuses.
- Raw provider errors are hidden under a collapsible Verification details section.

## Free-tier Case Intelligence Engine
Private Case Workspace now uses a single **Analyze / Update Case** workflow. It performs local hybrid retrieval (MiniLM + FAISS + BM25/RRF + cross-encoder), sends only a compact diverse set of relevant excerpts to the analysis model, and saves one Case Intelligence record. Overview, Timeline, Evidence, Contradictions, and Case Brief reuse that record without additional LLM calls. Uploading/removing a private PDF changes the document fingerprint and marks the saved intelligence stale. Ask LEXAI, Argument Builder, and Moot Court remain dynamic because their questions/issues vary.

## Central LLM routing (Gemini + Groq)

LEXAI now centralizes provider/model selection in `llm_router.py`.

- Citation cross-check: `GEMINI_VERIFY_MODEL` (default `gemini-3.5-flash-lite`)
- Case Intelligence extraction: `GEMINI_EXTRACTION_MODEL` (default `gemini-3.5-flash-lite`)
- Moot Court bench/judicial reasoning: `GEMINI_REASONING_MODEL` (default `gemini-3.8-flash`)
- Temporary Gemini capacity/rate/server failures are retried with backoff and jitter before Groq resilience fallback.
- Provider metadata records which provider/model actually generated a Moot Court or Case Intelligence result.
- `/health` exposes provider configuration/SDK/model status without consuming API quota.

Add `GEMINI_API_KEY` to `.env` to enable Gemini. The application still operates with Groq fallbacks when Gemini is unavailable.

## Frontend V3 UX refresh

The current build includes a dedicated LEXAI Frontend V3 pass: simplified Advocate/Citizen navigation, Advocate workspace sidebar, redesigned My Cases cards and permanent case deletion confirmation, sidebar-based private Case Workspace, Case Intelligence dashboard, visual Timeline/Evidence/Contradictions, private PDF source viewer, cleaner Ask LEXAI scope controls, improved Argument/Moot/Notebook views, system-health popover, responsive layouts, semantic status colors, motion with reduced-motion support, toasts, empty/error states, and removal of duplicate primary controls.

Permanent case deletion also clears private documents, private retrieval artifacts, saved notes, and cached Case Intelligence for the authenticated owner.

## Combined Knowledge Base UX update
- Global Advocate Research now uses a compact Judgment RAG ON/OFF switch. ON is the default and uses the indexed judgment corpus; OFF bypasses corpus retrieval without deleting/rebuilding it. New Research resets RAG to ON.
- The old large Research Source card and Global "Both" control were removed. Private Case Workspace still retains Case Documents / Judgments / Both.
- Upload Judgments now opens a staged modal with PDF validation, duplicate detection, drag/drop, per-file status, optional explicit replacement/re-indexing, and compact toast feedback.
- Existing judgment replacement removes the old indexed chunks only after the replacement PDF parses successfully, preventing accidental loss from a bad replacement upload.

## RAG Quality Lab V2
Developer > RAG Inspector now evaluates unique judgments rather than duplicate chunks. It supports canonical judgment matching, configurable candidate pools/RRF/reranking, per-question HIT/MISS diagnostics, candidate journeys, benchmark JSON/CSV import, and experiment export. RAG Lab is offline and does not call Groq or Gemini. Experiment settings do not change production Advocate Research.

## RAG 100-question benchmark update
RAG Lab can now generate a reproducible 100-question offline retrieval benchmark directly from the judgment records loaded by the local FAISS index (`GET /rag/benchmark/generate`). Generated items are grounded in real indexed passages and source judgments, carry category/difficulty metadata, graded relevance, and are explicitly marked `needs_human_review` before academic reporting. Evaluation now reports Hit@K, Precision@K, Recall@K, MRR, nDCG@K and independently measured stage latency. Normal Advocate Research settings are unchanged.

## Benchmark Runner (progress/cancel/cache)
The offline 100-question RAG benchmark now runs as a background job. RAG Lab shows real backend progress, elapsed time, ETA, current retrieval stage, and cache hits. The run can be cancelled safely; completed per-question retrieval results remain cached in memory and are reused when the same benchmark/settings are run again. Changing retrieval settings creates different cache keys. No Groq/Gemini calls are used by this runner.

## RAG Evaluation V3

RAG Lab now uses canonical exact ground-truth resolution after filename normalization. Fuzzy aliases no longer expand a single labelled judgment into unrelated relevant judgments. Multiple relevance is counted only when explicitly labelled in the benchmark.

The offline benchmark compares six pipelines on the same questions: FAISS only, BM25 only, Legacy RRF, Legacy Full reranked, Improved weighted fusion, and Improved Full RAG. Improved evaluation defaults use dense weight 1.0, BM25 weight 1.35, five sparse-rescue judgments, and rerank stability 0.25. Exports include `evaluator_version`, strategy names, Hit@1, Hit@K, Precision@K, Recall@K, MRR, nDCG@K, latency, and the experiment settings.

## Optional scanned-PDF OCR fallback
LEXAI keeps native PDF text extraction as the default. Pages with too little/poor text are OCR-processed individually and merged back at the original page number before the existing cleaning/chunking/RAG pipeline. Judgment uploads and Private Case PDFs share this extractor. Set `OCR_ENABLED=false` to disable it. OCR requires `pytesseract`, `Pillow`, PyMuPDF, and a system Tesseract installation; missing OCR support does not prevent native-text PDFs from working.

## V4.1 Safe Adaptive Retrieval
- Adds `adaptive` alongside `legacy` and `improved` retrieval strategies.
- Local legal query classification (statutory, citation, semantic, advocate, mixed); no LLM/API call.
- Deterministic legal query enrichment for common statutes/aliases.
- Query-type-specific dense/BM25 fusion weights.
- Retrieval-agreement protection prevents candidates ranked Top-3 by both FAISS and BM25 from being destructively demoted below rank 3 during adaptive reranking.
- RAG Lab adds `Adaptive fusion V4.1` and `Adaptive Full RAG V4.1` for direct A/B evaluation.
- Existing strategies remain available for rollback.

## V4.2 Legal Query Intelligence
V4.2 keeps Adaptive V4.1 ranking intact and adds local legal-query analysis (statutes/sections/articles/courts/case names), deterministic statute-aware sparse-query enrichment, ambiguity flags for underspecified section queries, and RAG Lab failure diagnostics that distinguish candidate-retrieval failures from ranking failures. No Groq/Gemini call is used for query routing or enrichment.

## V4.2.1 Legal Query Parser Hardening
- The recommended default retrieval strategy is improved (`RAG_RETRIEVAL_STRATEGY=improved`).
- Normalizes Section/Sec./S./s./§ and Article/Art. citation variants.
- Recognizes subsection-only forms such as `section (1-A)` as incomplete/ambiguous rather than silently treating them as generic text.
- Canonical statute aliases include IPC, CrPC, NI Act, BNSS, BNS, ESI, EPF and historical Workmen's/Employees' Compensation naming.
- Adds conservative OCR-tolerant recognition for corrupted statute names such as split/hyphenated Workmen's Compensation Act text.
- Adaptive BM25 in RAG Lab now evaluates the same enriched query used by production adaptive retrieval.
- Failure diagnostics distinguish `ambiguous_query`, `candidate_retrieval_failure`, `fusion_failure`, `reranking_failure`, and `final_top_k_failure`.
- Existing legacy and improved strategies remain available for rollback/A-B testing.

## V4.4 - Attribution-Aware Citation Verification
- Adds deterministic speaker-attribution verification after passage-support verification.
- Uses V4.3 legal-role metadata to distinguish Court reasoning/ratio/final orders from party submissions.
- Flags `attribution.status=mismatch` when an answer says the Court held a proposition but the supporting passage is a party argument.
- Returns `supported`, `mismatch`, or `uncertain` without converting uncertain classification into an unsupported citation.
- Advocate Research UI displays attribution status separately from claim support and precedent history.

## Unified Product-Readiness Release
This consolidated build keeps Adaptive V4.1 retrieval stable and adds the trust/reliability layer in one package:
- V4.3 legal-role intelligence and V4.4 attribution verification retained.
- Explainable evidence-strength score derived from corpus existence, passage support, verifier agreement, independent cross-check and legal-role attribution. This is not a legal-validity/citator score.
- Verification overview includes authority counts and authorities requiring review, providing groundwork for multi/contrary-authority analysis.
- Case-brief contradiction schema supports timeline, amount, identity, event, legal-position and other conflicts with source A/source B fields.
- `/health` now exposes runtime diagnostics, retrieval strategy, providers and indexed chunk count without consuming provider quota.
- `smoke_test.py` provides quick local non-provider checks; it does not replace end-to-end tests with the real corpus/API keys.

Quick check: `python smoke_test.py`.

## Final product step: Case -> Issue -> Evidence -> Law
Private Case Intelligence now includes an **Issue Map** workspace. After running **Analyze Case**, open **Issue Map** and choose **Build Issue Map**. LEXAI links extracted legal issues to private evidence with filename/page provenance, retrieves global judgment authorities, and separates supporting from contrary/distinguishable and related authorities. The map is cached against the private document fingerprint and becomes stale when case documents change. Authority stance is AI-assisted; later precedent treatment still requires an authoritative citator.

API:
- `GET /cases/{case_id}/issue-map`
- `POST /cases/{case_id}/issue-map/build`

## Dual-provider task-aware routing (final build)

LEXAI now uses a shared provider router instead of relying on Groq for every AI task.

- **Moot Court / Case Intelligence / Issue Map:** Gemini primary, Groq fallback.
- **Short interactive generation:** Groq primary, Gemini fallback where wired through the shared router.
- **Retrieval and RAG Lab:** remain local; no provider call is required for FAISS/BM25/Adaptive retrieval evaluation.
- Feature-specific output budgets prevent Moot Court from requesting 1500 output tokens against a 1000-OTPM Groq tier. Default Moot Court budget is 700.
- Provider results include provider/model, fallback status/reason, token budget and latency metadata where the feature exposes generation metadata.

Configure both `GEMINI_API_KEY` and `GROQ_API_KEY` for best resilience. Either provider can keep Moot Court available if the other is unavailable. Model IDs and token budgets are configurable in `.env`.

## Production persistence (Supabase)
The Render-Free build can use persistent Supabase PostgreSQL + private Storage without deploying the 848-judgment research corpus. Run `supabase/schema.sql`, keep the `lexai-private` bucket private, set `LEXAI_STORAGE_BACKEND=supabase`, and configure the backend-only Supabase Secret/service-role key in Render. See `SUPABASE_DEPLOYMENT.md`.

## Private Evidence Verification
Private Case Q&A now verifies generated claims against retrieved uploaded-document passages. It reports source filename/page, case-document role, allegation/testimony/direct-evidence attribution, multi-document corroboration, conservative contradiction signals, and evidence strength. Judgment Q&A retains the existing judgment citation/attribution verification policy. Production can run with the global 848-judgment corpus disabled; private evidence verification remains available.

## Production Case Intelligence reliability
Analyze Case uses a short 202 job-start request plus status polling. Existing cached analysis is preserved until a replacement analysis completes. The public `/` and `/health` endpoints are safe for Render probes, and production UI avoids global `/documents` when the research corpus is disabled.

## Production document research
When the global research corpus is disabled, the production UI switches from Global Research to Document Research. Authenticated users can upload a judgment, court order, or case PDF from the landing page. LEXAI creates a private workspace, indexes the PDF, opens Ask LEXAI, and verifies answers against document/page/passage provenance. The research-only global corpus remains available only when GLOBAL_JUDGMENT_CORPUS_ENABLED=true.

### Feedback-aware retrieval learning
LEXAI includes a bounded contextual-bandit layer. Explicit thumbs-up/down and
"Correct source" feedback are stored as reward events. After a minimum number
of events, retrieval weights/source priors receive small bounded adjustments.
Citation and evidence verification are never altered by this learned policy.
Production Supabase deployments should run the latest `supabase/schema.sql` to
create the `rag_feedback` table.
