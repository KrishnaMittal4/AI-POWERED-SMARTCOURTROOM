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
