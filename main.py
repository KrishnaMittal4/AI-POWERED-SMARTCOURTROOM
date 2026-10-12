"""
FastAPI Backend
================
Exposes the RAG pipeline (retrieval -> generation -> citation verification)
as a REST API for the React frontend.

Setup:
    pip install -r requirements.txt
    cp .env.example .env   # add your GROQ_API_KEY
    python rag_pipeline.py # builds the FAISS index once (needed before this)

Run:
    uvicorn main:app --reload --port 8000

Then open http://localhost:8000/docs for interactive API docs, or point
the React frontend at http://localhost:8000.
"""

import json
import logging
import os
import glob
import threading
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

from fastapi import Depends, FastAPI, HTTPException, Query, Request, UploadFile, File
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import faiss
import groq
import numpy as np
from groq import Groq

from rag_pipeline import (
    load_index, load_embedding_model, load_reranker_model, save_index,
    INDEX_DIR, JUDGMENTS_DIR, extract_text_and_head, clean_text,
    extract_metadata, chunk_text, build_contextual_header, build_or_load_bm25,
    build_faiss_index
)
from generate_answer import answer_query, answer_query_stream
from feedback_store import FeedbackStore
from similar_cases import find_similar, UnknownDocument
from moot_court import run_moot_court_debate, answer_interlocutory_query, run_human_counsel_debate, reply_human_counsel
from security import rate_limited, require_admin


load_dotenv()

# Holds the loaded index/model/client so they're loaded ONCE at startup,
# not on every request (loading the embedding model per-request would be
# far too slow).
state = {}
feedback = FeedbackStore()
index_lock = threading.RLock()   # serialises admin changes to the index (upload / delete)

MAX_UPLOAD_FILES = int(os.getenv("MAX_UPLOAD_FILES", "20"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "30"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        raise RuntimeError("GROQ_API_KEY not set. Copy .env.example to .env and add your key.")

    print("Loading FAISS index...")
    index, records, model_name = load_index(INDEX_DIR)

    print(f"Loading embedding model '{model_name}'...")
    embed_model = load_embedding_model(model_name)

    print("Loading Cross-Encoder re-ranker (cross-encoder/ms-marco-MiniLM-L-6-v2)...")
    reranker = load_reranker_model()
    if reranker is None:
        print("  Re-ranker unavailable -- falling back to RRF-only ranking.")

    state["index"] = index
    state["records"] = records
    state["embed_model"] = embed_model
    state["model_name"] = model_name
    state["reranker"] = reranker
    state["groq_client"] = Groq(api_key=groq_key)
    print("Startup complete. API ready.")

    yield
    # --- shutdown --- (nothing to clean up currently)
    state.clear()


app = FastAPI(title="Legal RAG API", lifespan=lifespan)

# Allow the React dev server (Vite default port 5173) to call this API
# from the browser during local development.
_cors_env = os.getenv("CORS_ORIGINS", "")
_cors_origins = (
    [o.strip() for o in _cors_env.split(",") if o.strip()]
    if _cors_env
    else [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
        "http://localhost:5175", "http://127.0.0.1:5175",
    ]
)

# If CORS_ORIGINS is set (production), ONLY those origins are allowed. The
# *.vercel.app wildcard is kept for first-time setup / local use when it is
# not set -- any Vercel app could otherwise call your API from a browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_origin_regex=None if _cors_env else r"https://.*\.vercel\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# GROQ ERRORS -> clean HTTP responses (never leak raw provider errors)
# ---------------------------------------------------------------------------
@app.exception_handler(groq.RateLimitError)
async def _groq_rate_limit(request: Request, exc: groq.RateLimitError):
    retry = "60"
    try:
        retry = str(int(float(exc.response.headers.get("retry-after", "60"))) + 1)
    except Exception:
        pass
    print(f"  Groq rate limit hit: {exc}")
    return JSONResponse(
        status_code=429,
        content={"detail": "The AI service is busy right now (rate limit reached). Please try again in a minute."},
        headers={"Retry-After": retry},
    )


@app.exception_handler(groq.APIStatusError)
@app.exception_handler(groq.APIConnectionError)
async def _groq_error(request: Request, exc: Exception):
    print(f"  Groq error: {type(exc).__name__}: {exc}")
    return JSONResponse(status_code=502, content={"detail": "The AI service had a problem. Please try again."})


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000, description="The legal question to ask")
    top_k: int = Field(3, ge=1, le=10, description="Number of passages to retrieve")
    verify: bool = Field(True, description="Whether to run citation verification")


class SourceOut(BaseModel):
    case_name: str
    source_file: str
    score: float
    case_no: str | None = None
    text: str = ""  # the retrieved passage, so the UI can show/highlight it


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceOut]
    verification: dict | None = None
    not_found: bool = False      # best passage was below MIN_RETRIEVAL_SCORE
    statutory_fallback: bool = False  # answered using general statutory principles when not in corpus
    top_score: float | None = None
    threshold: float | None = None  # MIN_RETRIEVAL_SCORE in force
    weak_match: bool = False     # answered, but best score was below WEAK_RETRIEVAL_SCORE
    rewritten_query: str | None = None  # the LLM-rewritten search query (if different from original)


@app.get("/health")
def health():
    return {"status": "ok", "chunks_indexed": len(state.get("records", []))}


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest, _rl: None = Depends(rate_limited())):
    if "index" not in state:
        raise HTTPException(status_code=503, detail="Index not loaded yet.")

    result = answer_query(
        query=req.question,
        index=state["index"],
        records=state["records"],
        embed_model=state["embed_model"],
        client=state["groq_client"],
        top_k=req.top_k,
        verify=req.verify,
        rerank=state.get("reranker") is not None,
        reranker_model=state.get("reranker"),
    )
    return result


# ---------------------------------------------------------------------------
# STREAMING ENDPOINT (SSE)
# ---------------------------------------------------------------------------
@app.post("/query/stream")
def query_stream(req: QueryRequest, _rl: None = Depends(rate_limited())):
    """Stream the RAG answer token-by-token via Server-Sent Events.

    The frontend connects with `new EventSource()` or `fetch()` and reads
    events as they arrive:
      event: sources       — retrieved passages (rendered immediately)
      event: token         — one LLM token at a time
      event: verification  — citation verification results (after generation)
      event: done          — full accumulated answer
      event: error         — something went wrong
    """
    if "index" not in state:
        raise HTTPException(status_code=503, detail="Index not loaded yet.")

    def event_generator():
        yield from answer_query_stream(
            query=req.question,
            index=state["index"],
            records=state["records"],
            embed_model=state["embed_model"],
            client=state["groq_client"],
            top_k=req.top_k,
            verify=req.verify,
            rerank=state.get("reranker") is not None,
            reranker_model=state.get("reranker"),
        )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering if proxied
        },
    )


# ---------------------------------------------------------------------------
# FEEDBACK ENDPOINTS
# ---------------------------------------------------------------------------
class FeedbackRequest(BaseModel):
    question: str = Field(..., max_length=1000)
    answer: str = Field(..., max_length=30000)
    rating: int = Field(..., ge=-1, le=1, description="1 = thumbs up, -1 = thumbs down")
    comment: str | None = Field(None, max_length=2000)
    top_score: float | None = None
    weak_match: bool = False
    not_found: bool = False


class FeedbackResponse(BaseModel):
    status: str
    id: int


@app.post("/feedback", response_model=FeedbackResponse)
def submit_feedback(
    req: FeedbackRequest,
    _rl: None = Depends(rate_limited("feedback", "FEEDBACK_RATE_PER_MIN", "FEEDBACK_RATE_PER_DAY",
                                     20, 200, use_global=False)),
):
    """Submit thumbs up/down feedback on an answer."""
    fid = feedback.add(
        question=req.question,
        answer=req.answer,
        rating=req.rating,
        comment=req.comment,
        top_score=req.top_score,
        weak_match=req.weak_match,
        not_found=req.not_found,
    )
    return {"status": "ok", "id": fid}


@app.get("/feedback/summary", dependencies=[Depends(require_admin)])
def feedback_summary():
    """Aggregate feedback stats."""
    return feedback.summary()


@app.get("/feedback/recent", dependencies=[Depends(require_admin)])
def feedback_recent(limit: int = Query(50, ge=1, le=500)):
    """Recent feedback entries (for admin/debug)."""
    return feedback.recent(limit)


# ---------------------------------------------------------------------------
# DOCUMENT MANAGEMENT ENDPOINTS
# ---------------------------------------------------------------------------
class DocumentOut(BaseModel):
    filename: str
    case_name: str | None = None
    court: str | None = None
    case_no: str | None = None
    chunk_count: int = 0


@app.get("/documents", response_model=list[DocumentOut])
def list_documents():
    """List all indexed documents with their metadata and chunk counts."""
    records = state.get("records", [])

    # Aggregate metadata per source file
    doc_map: dict[str, dict] = {}
    for r in records:
        fname = r.get("source_file", "")
        if fname not in doc_map:
            doc_map[fname] = {
                "filename": fname,
                "case_name": r.get("case_name"),
                "court": r.get("court"),
                "case_no": r.get("case_no"),
                "chunk_count": 0,
            }
        doc_map[fname]["chunk_count"] += 1

    # Also include any PDFs in the judgments/ folder that aren't indexed yet
    if os.path.isdir(JUDGMENTS_DIR):
        for pdf_path in glob.glob(os.path.join(JUDGMENTS_DIR, "*.pdf")) + glob.glob(os.path.join(JUDGMENTS_DIR, "*.PDF")):
            fname = os.path.basename(pdf_path)
            if fname not in doc_map:
                doc_map[fname] = {
                    "filename": fname,
                    "case_name": None,
                    "court": None,
                    "case_no": None,
                    "chunk_count": 0,
                }

    return sorted(doc_map.values(), key=lambda d: d["filename"])


class SimilarRequest(BaseModel):
    source_file: str | None = Field(None, max_length=300, description="Judgment to find neighbours of (excluded from results)")
    text: str | None = Field(None, max_length=4000, description="Optional passage; if given, search by this text instead of the whole judgment")
    limit: int = Field(8, ge=1, le=20)


class SimilarCaseOut(BaseModel):
    source_file: str
    case_name: str | None = None
    case_no: str | None = None
    court: str | None = None
    decision_date: str | None = None
    score: float                    # similarity of the document's best-matching chunk
    matched_chunks: int             # how many of the top-500 chunk hits fall in this document
    snippet: str = ""
    text: str = ""


class SimilarResponse(BaseModel):
    basis: str                      # "passage" or "document"
    source_file: str | None = None
    results: list[SimilarCaseOut]


@app.post("/similar", response_model=SimilarResponse)
def similar_cases(
    req: SimilarRequest,
    _rl: None = Depends(rate_limited("similar", "SIMILAR_RATE_PER_MIN", "SIMILAR_RATE_PER_DAY",
                                     30, 500, use_global=False)),
):
    """Judgments similar to a passage or to a whole judgment, grouped by document
    (one row per case, ranked by its best-matching passage). No LLM call."""
    if "index" not in state:
        raise HTTPException(status_code=503, detail="Index not loaded yet.")
    if not (req.text and req.text.strip()) and not req.source_file:
        raise HTTPException(status_code=422, detail="Provide `text` or `source_file`.")
    try:
        return find_similar(
            state["index"], state["records"], state["embed_model"],
            source_file=req.source_file, text=req.text, limit=req.limit,
        )
    except UnknownDocument:
        raise HTTPException(status_code=404, detail=f"'{req.source_file}' is not in the index.")


@app.get("/documents/{filename}/chunks")
def get_document_chunks(filename: str):
    """Return all indexed chunks for a specific document."""
    records = state.get("records", [])
    chunks = [
        {
            "chunk_id": r["chunk_id"],
            "text": r.get("raw_text", r.get("text", "")),
            "case_name": r.get("case_name"),
            "case_no": r.get("case_no"),
        }
        for r in records
        if r.get("source_file") == filename
    ]
    if not chunks:
        raise HTTPException(status_code=404, detail=f"No chunks found for '{filename}'")
    return {"filename": filename, "chunk_count": len(chunks), "chunks": chunks}


@app.delete("/documents/{filename}", dependencies=[Depends(require_admin)])
def delete_document(filename: str):
    """Remove a document from the index (admin only).

    The stored vectors of the remaining chunks are kept (FAISS reconstruct),
    so nothing is re-embedded -- deleting from a 60,000-chunk index takes
    seconds, not minutes. The new index is saved BEFORE it replaces the
    in-memory one, so a failed save leaves the running server unchanged.
    """
    if "index" not in state:
        raise HTTPException(status_code=503, detail="Index not loaded yet.")

    with index_lock:
        records = state["records"]
        old_index = state["index"]
        if old_index.ntotal != len(records):
            raise HTTPException(status_code=500, detail="Index and records are out of sync; restart the server.")

        keep_rows = [i for i, r in enumerate(records) if r.get("source_file") != filename]
        removed_count = len(records) - len(keep_rows)
        if removed_count == 0:
            raise HTTPException(status_code=404, detail=f"No indexed chunks found for '{filename}'")

        if keep_rows:
            vectors = old_index.reconstruct_n(0, old_index.ntotal)
            new_index = build_faiss_index(np.ascontiguousarray(vectors[keep_rows], dtype="float32"))
        else:
            new_index = faiss.IndexFlatIP(old_index.d)
        new_records = [records[i] for i in keep_rows]

        stale_bm25 = os.path.join(INDEX_DIR, "bm25.pkl")
        if os.path.exists(stale_bm25):
            os.remove(stale_bm25)
        save_index(new_index, new_records, state.get("model_name", "all-MiniLM-L6-v2"))
        state["index"], state["records"] = new_index, new_records

    pdf_path = os.path.join(JUDGMENTS_DIR, os.path.basename(filename))
    pdf_deleted = False
    if os.path.exists(pdf_path):
        try:
            os.remove(pdf_path)
            pdf_deleted = True
        except Exception:
            pass

    return {
        "status": "ok",
        "message": f"Removed {removed_count} chunks for '{filename}'.",
        "chunks_removed": removed_count,
        "total_chunks": len(new_records),
        "pdf_deleted": pdf_deleted,
    }


# ---------------------------------------------------------------------------
# UPLOAD ENDPOINT (existing, preserved)
# ---------------------------------------------------------------------------
class UploadResponse(BaseModel):
    status: str
    message: str
    uploaded_files: list[str]
    new_chunks_count: int
    total_chunks: int
    skipped: list[str] = []
    suggested_questions: list[str] = []
    source_filename: str = ""


def generate_sample_questions_for_doc(text_sample: str, meta: dict, client) -> list[str]:
    """Generate 4 focused legal questions directly answerable from this uploaded judgment."""
    case_name = meta.get("case_name") or "the judgment"
    court = meta.get("court") or "Court"
    prompt = (
        f"You are a senior Indian legal advocate and researcher.\n"
        f"Review this judgment text excerpt from '{case_name}' ({court}):\n\n"
        f"\"\"\"{text_sample[:3200]}\"\"\"\n\n"
        f"Generate exactly 4 insightful, specific legal questions that an advocate or researcher would ask "
        f"about this exact case. The questions should focus on the core legal issues decided, statutory provisions interpreted, "
        f"or the court's core ratio decidendi.\n"
        f"Return ONLY a valid JSON array of 4 question strings. Example:\n"
        f"[\"What was the court's finding on...?\", \"How did the court interpret Section...?\", ...]"
    )
    try:
        completion = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[
                {"role": "system", "content": "You are a legal research assistant. Always output a pure JSON list of strings."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=400,
        )
        raw = completion.choices[0].message.content.strip()
        if "```json" in raw:
            raw = raw.split("```json")[1].split("```")[0].strip()
        elif "```" in raw:
            raw = raw.split("```")[1].split("```")[0].strip()
        questions = json.loads(raw)
        if isinstance(questions, list) and len(questions) >= 2:
            return [str(q).strip() for q in questions[:4] if str(q).strip()]
    except Exception as e:
        logger.warning(f"Error in LLM question generation: {e}")

    # Fallback based on metadata
    clean_name = meta.get("case_name") or "this case"
    return [
        f"What was the core ratio decidendi and final decision in {clean_name}?",
        f"Which statutory provisions and precedents were primarily relied upon in {clean_name}?",
        f"What were the key submissions and arguments raised by the parties?",
        f"What legal doctrine or standard of proof was reaffirmed by the court in {clean_name}?",
    ]


def _ingest_pdf(contents: bytes, filename: str):
    """Save one uploaded PDF and turn it into chunk records. Runs in a worker
    thread (PDF parsing is CPU-bound). Returns (records, skip_reason)."""
    save_path = os.path.join(JUDGMENTS_DIR, filename)
    with open(save_path, "wb") as f:
        f.write(contents)
    raw_full, raw_head = extract_text_and_head(save_path)
    cleaned = clean_text(raw_full)
    if not cleaned:
        os.remove(save_path)
        return [], "no extractable text (scanned image?)"

    meta = extract_metadata(cleaned, filename, raw_head=raw_head)
    header = build_contextual_header(meta)
    records = []
    for i, chunk in enumerate(chunk_text(cleaned)):
        records.append({
            "chunk_id": f"{filename}::chunk{i}",
            "text": f"{header}\n{chunk}" if header else chunk,
            "raw_text": chunk,
            "case_name": meta["case_name"],
            "court": meta["court"],
            "case_no": meta["case_no"],
            "neutral_citation": meta.get("neutral_citation"),
            "decision_date": meta.get("decision_date"),
            "bench": meta.get("bench"),
            "scr_citation": meta.get("scr_citation"),
            "source_file": filename,
        })
    return records, None


def _commit_records(new_records: list):
    """Embed and add new chunks to the live index (admin only, one at a time)."""
    with index_lock:
        embeddings = state["embed_model"].encode(
            [r["text"] for r in new_records], batch_size=64, show_progress_bar=False,
            convert_to_numpy=True, normalize_embeddings=True,
        ).astype("float32")

        index = state["index"]
        all_records = list(state["records"]) + new_records

        # Rebuild BM25 for the new record list BEFORE publishing it, so queries
        # arriving mid-upload hit the cache instead of rebuilding it themselves.
        stale_bm25 = os.path.join(INDEX_DIR, "bm25.pkl")
        if os.path.exists(stale_bm25):
            os.remove(stale_bm25)
        build_or_load_bm25(all_records, index_dir=INDEX_DIR)

        # Publish records first, vectors second: a query that races in between
        # sees records without vectors (harmless, they only match via BM25)
        # rather than vectors without records (an IndexError).
        state["records"] = all_records
        index.add(embeddings)
        save_index(index, all_records, state.get("model_name", "all-MiniLM-L6-v2"))
        return len(all_records)


@app.post("/upload", response_model=UploadResponse)
async def upload_files(files: list[UploadFile] = File(...)):
    """Upload judgment PDFs and index them incrementally.

    Rejects non-PDFs, files over MAX_UPLOAD_MB, more than MAX_UPLOAD_FILES per
    call, and filenames that are already indexed (delete the old one first --
    re-adding the same name would silently duplicate its chunks).
    """
    if "index" not in state:
        raise HTTPException(status_code=503, detail="Index not loaded yet.")
    if len(files) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=413, detail=f"At most {MAX_UPLOAD_FILES} files per upload.")

    os.makedirs(JUDGMENTS_DIR, exist_ok=True)
    existing = {r["source_file"] for r in state["records"]}
    saved, skipped, new_records = [], [], []

    for file in files:
        filename = os.path.basename(file.filename or "")
        if not filename.lower().endswith(".pdf") or filename.startswith("."):
            skipped.append(f"{filename or '(no name)'}: not a PDF")
            continue
        if filename in existing or filename in saved:
            skipped.append(f"{filename}: already indexed (delete it first to replace it)")
            continue
        contents = await file.read()
        if len(contents) > MAX_UPLOAD_MB * 1024 * 1024:
            skipped.append(f"{filename}: larger than {MAX_UPLOAD_MB} MB")
            continue
        if not contents.startswith(b"%PDF"):
            skipped.append(f"{filename}: not a valid PDF file")
            continue
        records, reason = await run_in_threadpool(_ingest_pdf, contents, filename)
        if reason:
            skipped.append(f"{filename}: {reason}")
            continue
        saved.append(filename)
        new_records.extend(records)

    if not new_records:
        return UploadResponse(
            status="ok",
            message="Nothing was indexed." + (" See 'skipped' for why." if skipped else ""),
            uploaded_files=saved, new_chunks_count=0,
            total_chunks=len(state["records"]), skipped=skipped,
        )

    suggested_questions = []
    if new_records and state.get("groq_client"):
        sample_text = "\n".join([r.get("raw_text", "") for r in new_records[:3]])
        meta_info = {
            "case_name": new_records[0].get("case_name"),
            "court": new_records[0].get("court")
        }
        suggested_questions = await run_in_threadpool(
            generate_sample_questions_for_doc, sample_text, meta_info, state["groq_client"]
        )

    total = await run_in_threadpool(_commit_records, new_records)
    return UploadResponse(
        status="ok",
        message=f"Indexed {len(saved)} file(s)" + (f", skipped {len(skipped)}." if skipped else "."),
        uploaded_files=saved, new_chunks_count=len(new_records),
        total_chunks=total, skipped=skipped,
        suggested_questions=suggested_questions,
        source_filename=saved[0] if saved else "",
    )


# ---------------------------------------------------------------------------
# LEGAL INTELLIGENCE ENDPOINTS
# ---------------------------------------------------------------------------
from legal_intelligence import (
    check_precedent_status,
    extract_ratio_and_obiter,
    generate_legal_draft,
    DRAFT_TEMPLATES,
    analyze_citizen_incident,
)


@app.get("/precedent/check")
def check_precedent(case_name: str = Query(..., min_length=2, max_length=300),
                     _rl: None = Depends(rate_limited())):
    """Check if a case is Good Law, Distinguished, or Overruled."""
    client = state.get("groq_client")
    return check_precedent_status(case_name, client)


class RatioObiterRequest(BaseModel):
    case_name: str = Field(..., max_length=300)
    passage: str = Field(..., max_length=8000)


@app.post("/analyze/ratio-obiter")
def analyze_ratio_obiter(req: RatioObiterRequest, _rl: None = Depends(rate_limited())):
    """Dissect a judgment passage into binding Ratio Decidendi and non-binding Obiter Dicta."""
    client = state.get("groq_client")
    if not client:
        raise HTTPException(status_code=503, detail="Groq client not initialized")
    return extract_ratio_and_obiter(req.case_name, req.passage, client)


@app.get("/draft/templates")
def list_draft_templates():
    """List available court-ready legal draft templates."""
    return [
        {"id": k, "title": v["title"], "description": v["description"], "forum": v["forum"]}
        for k, v in DRAFT_TEMPLATES.items()
    ]


class DraftRequest(BaseModel):
    draft_type: str = Field("ni_act_138", description="Template key from /draft/templates")
    facts: str = Field(..., max_length=8000, description="Factual background or client instructions")
    citations: list[str] = Field(default_factory=list, max_length=20, description="List of precedents to incorporate")
    petitioner: str | None = Field(None, max_length=200, description="Complainant / Petitioner name")
    respondent: str | None = Field(None, max_length=200, description="Accused / Respondent name")


@app.post("/draft/generate")
def generate_court_draft(req: DraftRequest, _rl: None = Depends(rate_limited())):
    """Generate a structured, court-ready Indian legal draft (Section 138, Bail, Recovery, etc.)."""
    if req.draft_type not in DRAFT_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Unknown draft_type. Choose one of: {sorted(DRAFT_TEMPLATES)}")
    client = state.get("groq_client")
    if not client:
        raise HTTPException(status_code=503, detail="Groq client not initialized")
    parties = {"petitioner": req.petitioner, "respondent": req.respondent}
    return generate_legal_draft(
        draft_type=req.draft_type,
        facts=req.facts,
        citations=req.citations,
        client=client,
        parties=parties,
    )


class CitizenAdviceRequest(BaseModel):
    incident: str = Field(..., min_length=10, max_length=5000, description="Everyday citizen incident or grievance")


@app.post("/citizen-advice")
def get_citizen_advice(req: CitizenAdviceRequest, _rl: None = Depends(rate_limited())):
    """Analyze everyday citizen legal problems and return applicable laws, rights, and action roadmap."""
    client = state.get("groq_client")
    if not client:
        raise HTTPException(status_code=503, detail="Groq client not initialized")
    return analyze_citizen_incident(
        incident=req.incident,
        client=client,
        index=state.get("index"),
        records=state.get("records"),
        embed_model=state.get("embed_model"),
    )


class MootCourtRequest(BaseModel):
    dispute: str = Field(..., min_length=10, max_length=4000, description="Legal proposition or case facts to debate")


@app.post("/moot-court")
def simulate_moot_court(
    req: MootCourtRequest,
    _rl: None = Depends(rate_limited("moot", "MOOT_RATE_PER_MIN", "MOOT_RATE_PER_DAY", 6, 100, use_global=False)),
):
    """Run an adversarial moot court debate: Petitioner (Groq) vs Respondent (Groq) vs Bench (Gemini)."""
    if "index" not in state:
        raise HTTPException(status_code=503, detail="Index not loaded yet.")
    client = state.get("groq_client")
    if not client:
        raise HTTPException(status_code=503, detail="Groq client not initialized")
    try:
        return run_moot_court_debate(
            dispute=req.dispute,
            index=state["index"],
            records=state["records"],
            embed_model=state["embed_model"],
            groq_client=client,
        )
    except Exception as e:
        logger.error(f"Moot court debate failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Moot court simulation failed: {str(e)}")


class InterlocutoryRequest(BaseModel):
    dispute: str = Field(..., max_length=4000)
    target_counsel: str = Field("respondent", description="petitioner or respondent")
    counsel_argument: str = Field(..., max_length=8000)
    judge_question: str = Field(..., min_length=3, max_length=2000)
    citations: list[dict] = Field(default_factory=list)


@app.post("/moot-court/interlocutory")
def interlocutory_question(
    req: InterlocutoryRequest,
    _rl: None = Depends(rate_limited("moot_q", "MOOT_Q_PER_MIN", "MOOT_Q_PER_DAY", 15, 200, use_global=False)),
):
    """Answer a judicial question posed from the Bench to either counsel."""
    client = state.get("groq_client")
    if not client:
        raise HTTPException(status_code=503, detail="Groq client not initialized")
    try:
        return answer_interlocutory_query(
            dispute=req.dispute,
            target_counsel=req.target_counsel,
            counsel_argument=req.counsel_argument,
            judge_question=req.judge_question,
            citations=req.citations,
            groq_client=client,
        )
    except Exception as e:
        logger.error(f"Interlocutory Q&A failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to query counsel: {str(e)}")


class HumanCounselRequest(BaseModel):
    dispute: str = Field(..., min_length=10, max_length=4000, description="Legal proposition or facts to debate")
    user_role: str = Field("petitioner", description="petitioner or respondent")
    user_argument: str = Field(..., min_length=15, max_length=8000, description="Oral submission drafted by human advocate")


@app.post("/moot-court/human-counsel")
def human_vs_ai_moot_court(
    req: HumanCounselRequest,
    _rl: None = Depends(rate_limited("moot_h", "MOOT_H_PER_MIN", "MOOT_H_PER_DAY", 6, 100, use_global=False)),
):
    """Run an interactive Human vs AI debate: Human Counsel vs AI Opponent vs Bench Scorecard & Verdict."""
    if "index" not in state:
        raise HTTPException(status_code=503, detail="Index not loaded yet.")
    client = state.get("groq_client")
    if not client:
        raise HTTPException(status_code=503, detail="Groq client not initialized")
    try:
        return run_human_counsel_debate(
            dispute=req.dispute,
            user_role=req.user_role,
            user_argument=req.user_argument,
            index=state["index"],
            records=state["records"],
            embed_model=state["embed_model"],
            groq_client=client,
        )
    except Exception as e:
        logger.error(f"Human vs AI moot court failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Human counsel session failed: {str(e)}")


class HumanReplyRequest(BaseModel):
    dispute: str = Field(..., min_length=10, max_length=4000)
    user_role: str = Field("petitioner", description="petitioner or respondent")
    user_reply: str = Field(..., min_length=5, max_length=4000, description="Human counsel's follow-up submission")
    round_number: int = Field(2, ge=2, le=10, description="Which round of the debate this is")
    prior_exchange: list[dict] = Field(default_factory=list, description="Previous turns for conversational context")


@app.post("/moot-court/human-reply")
def human_counsel_reply(
    req: HumanReplyRequest,
    _rl: None = Depends(rate_limited("moot_r", "MOOT_R_PER_MIN", "MOOT_R_PER_DAY", 12, 200, use_global=False)),
):
    """Handle a follow-up rebuttal from the Human Advocate in a live multi-turn debate."""
    if "index" not in state:
        raise HTTPException(status_code=503, detail="Index not loaded yet.")
    client = state.get("groq_client")
    if not client:
        raise HTTPException(status_code=503, detail="Groq client not initialized")
    try:
        return reply_human_counsel(
            dispute=req.dispute,
            user_role=req.user_role,
            user_reply=req.user_reply,
            round_number=req.round_number,
            prior_exchange=req.prior_exchange,
            index=state["index"],
            records=state["records"],
            embed_model=state["embed_model"],
            groq_client=client,
        )
    except Exception as e:
        logger.error(f"Human counsel reply failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Debate reply failed: {str(e)}")