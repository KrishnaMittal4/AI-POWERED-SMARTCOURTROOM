from fastapi.responses import FileResponse
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

from llm_router import provider_status, call_groq, call_gemini, gemini_configured
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

from legal_judgment_intelligence import annotate_record
from rag_pipeline import (
    load_index, load_embedding_model, load_reranker_model, save_index,
    INDEX_DIR, JUDGMENTS_DIR, extract_text_and_head, clean_text,
    extract_metadata, chunk_text, build_contextual_header, build_or_load_bm25,
    build_faiss_index
)
from generate_answer import answer_query, answer_query_stream
from feedback_store import FeedbackStore
from feedback_learning import query_type as feedback_query_type, profile_adjustment as feedback_profile_adjustment
from similar_cases import find_similar, UnknownDocument
from moot_court import run_moot_court_debate, answer_interlocutory_query, run_human_counsel_debate, reply_human_counsel
from security import rate_limited, require_admin
from auth import init_auth_db, create_user, authenticate, make_token, current_user
from case_workspace import init_case_db, list_cases, create_case, delete_case, list_documents as list_case_documents, get_document_path, save_documents, delete_document as delete_case_document
from private_case_rag import ask_case, analyze_case
from case_intelligence import init_intelligence_db, list_notes, add_note, delete_note, overview, build_argument
from case_engine import init_case_engine_db, get_intelligence, analyze_once, section as intelligence_section, brief as intelligence_brief
from case_law_mapping import init_issue_map_db, get_issue_map, build_issue_map
from rag_evaluation import inspect_query, evaluate as evaluate_retrieval, generate_benchmark, generate_realistic_benchmark
from benchmark_runner import start as start_benchmark_job, get as get_benchmark_job, cancel as cancel_benchmark_job, result as benchmark_job_result
from case_analysis_jobs import start as start_case_analysis_job, get as get_case_analysis_job
import supabase_repository as supabase_repo


load_dotenv()

# Holds the loaded index/model/client so they're loaded ONCE at startup,
# not on every request (loading the embedding model per-request would be
# far too slow).
state = {}
feedback = FeedbackStore()
index_lock = threading.RLock()   # serialises admin changes to the index (upload / delete)

LEXAI_ENV = os.getenv("LEXAI_ENV", "development").strip().lower()
RENDER_FREE_MODE = os.getenv("LEXAI_RENDER_FREE_MODE", "false").strip().lower() in {"1","true","yes","on"}
LOW_MEMORY_MODE = os.getenv("LEXAI_LOW_MEMORY_MODE", "true" if RENDER_FREE_MODE else "false").strip().lower() in {"1","true","yes","on"}
MAX_UPLOAD_FILES = int(os.getenv("MAX_UPLOAD_FILES", "5" if RENDER_FREE_MODE else "20"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "8" if RENDER_FREE_MODE else "30"))

# Render Free is a public/demo profile: research-only assets must never become a
# startup dependency even if a stale environment variable says otherwise.
GLOBAL_CORPUS_ENABLED = False if RENDER_FREE_MODE else os.getenv("GLOBAL_JUDGMENT_CORPUS_ENABLED", "true" if LEXAI_ENV != "production" else "false").strip().lower() in {"1","true","yes","on"}
DEVELOPER_TOOLS_ENABLED = False if RENDER_FREE_MODE else os.getenv("ENABLE_DEVELOPER_TOOLS", "true" if LEXAI_ENV != "production" else "false").strip().lower() in {"1","true","yes","on"}

def _require_global_corpus():
    if not GLOBAL_CORPUS_ENABLED or state.get("index") is None:
        raise HTTPException(status_code=503, detail="Global judgment research corpus is not enabled in this deployment. Use Private Cases or General AI mode.")

def _require_developer_tools():
    if not DEVELOPER_TOOLS_ENABLED:
        raise HTTPException(status_code=404, detail="Developer tools are disabled in this deployment.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- startup ---
    init_auth_db()
    init_case_db()
    init_intelligence_db()
    init_case_engine_db()
    init_issue_map_db()
    groq_key = os.getenv("GROQ_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    if not groq_key and not gemini_key:
        raise RuntimeError("Set at least one AI provider key: GROQ_API_KEY or GEMINI_API_KEY.")

    index, records = None, []
    model_name = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    if GLOBAL_CORPUS_ENABLED:
        print("Loading global research FAISS index...")
        index, records, model_name = load_index(INDEX_DIR)
    else:
        print("Production mode: global 848-judgment research corpus is disabled.")

    if LOW_MEMORY_MODE:
        print(f"Low-memory mode: embedding model '{model_name}' will lazy-load on first private RAG use.")
        embed_model = None
        reranker = None
        print("Low-memory mode: resident Cross-Encoder disabled; hybrid FAISS+BM25 fusion remains enabled.")
    else:
        print(f"Loading embedding model '{model_name}' for private-case RAG...")
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
    state["groq_client"] = Groq(api_key=groq_key) if groq_key else None
    print("Startup complete. API ready.")

    yield
    # --- shutdown --- (nothing to clean up currently)
    state.clear()


from product_readiness import runtime_diagnostics

app = FastAPI(title="Legal RAG API", lifespan=lifespan)

# Allow the React dev server (Vite default port 5173) to call this API
# from the browser during local development.
_cors_env = os.getenv("CORS_ORIGINS", "").strip()

# Handle wildcard "*" explicitly — Starlette requires allow_all_origins=True
# for a true wildcard, not allow_origins=["*"]
if _cors_env == "*":
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
elif _cors_env:
    _cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_origin_regex=None,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    # Development / first-time setup: allow localhost + any *.vercel.app
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://localhost:5174", "http://127.0.0.1:5174",
            "http://localhost:5175", "http://127.0.0.1:5175",
        ],
        allow_origin_regex=r"https://.*\.vercel\.app",
        allow_methods=["*"],
        allow_headers=["*"],
    )



@app.middleware("http")
async def require_signed_in_user(request: Request, call_next):
    path = request.url.path
    public = path in {"/", "/health", "/ping", "/docs", "/openapi.json", "/redoc"} or path.startswith("/auth/")
    if not public and request.method != "OPTIONS":
        try:
            current_user(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)

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


class AuthSignupRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)


class AuthLoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=8, max_length=128)


@app.post("/auth/signup")
def auth_signup(req: AuthSignupRequest):
    if "@" not in req.email or "." not in req.email.rsplit("@", 1)[-1]:
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    user = create_user(req.name, req.email, req.password)
    return {"token": make_token(user), "user": user}


@app.post("/auth/login")
def auth_login(req: AuthLoginRequest):
    user = authenticate(req.email, req.password)
    return {"token": make_token(user), "user": user}


@app.get("/auth/me")
def auth_me(user: dict = Depends(current_user)):
    return {"user": user}


class CaseCreateRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=120)
    description: str = Field('', max_length=1000)


@app.get("/cases")
def cases_list(user: dict = Depends(current_user)):
    return {"cases": list_cases(user["id"])}


@app.post("/cases")
def cases_create(req: CaseCreateRequest, user: dict = Depends(current_user)):
    return {"case": create_case(user["id"], req.title, req.description)}


@app.delete("/cases/{case_id}")
def cases_delete(case_id: str, user: dict = Depends(current_user)):
    delete_case(user["id"], case_id)
    return {"ok": True}


@app.get("/cases/{case_id}/documents")
def case_documents(case_id: str, user: dict = Depends(current_user)):
    return {"documents": list_case_documents(user["id"], case_id)}


@app.post("/cases/{case_id}/documents")
async def case_documents_upload(case_id: str, files: list[UploadFile] = File(...), user: dict = Depends(current_user)):
    if len(files) > MAX_UPLOAD_FILES: raise HTTPException(400, f"Upload at most {MAX_UPLOAD_FILES} files at once.")
    return {"documents": await save_documents(user["id"], case_id, files, MAX_UPLOAD_MB)}



@app.get("/cases/{case_id}/documents/{document_id}/file")
def case_document_file(case_id: str, document_id: str, user: dict = Depends(current_user)):
    path, original_name = get_document_path(user["id"], case_id, document_id)
    return FileResponse(path, media_type="application/pdf", filename=original_name, content_disposition_type="inline")

@app.delete("/cases/{case_id}/documents/{document_id}")
def case_documents_delete(case_id: str, document_id: str, user: dict = Depends(current_user)):
    delete_case_document(user["id"], case_id, document_id)
    return {"ok": True}


class CaseQueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000)
    mode: str = Field("case", pattern="^(case|global|both)$")
    top_k: int = Field(3, ge=1, le=8)
    verify: bool = True

@app.post("/cases/{case_id}/query")
async def case_query(case_id: str, req: CaseQueryRequest, user: dict = Depends(current_user), _rl: None = Depends(rate_limited("case_query", "CASE_QUERY_PER_MIN", "CASE_QUERY_PER_DAY", 12, 200, use_global=False))):
    return await run_in_threadpool(ask_case, user["id"], case_id, req.question, req.mode, req.top_k, req.verify,
        state.get("embed_model"), state.get("reranker"), state["groq_client"],
        state.get("index"), state.get("records"))

@app.get("/cases/{case_id}/intelligence")
def case_intelligence_get(case_id: str, user: dict = Depends(current_user)):
    return get_intelligence(user["id"], case_id)

@app.post("/cases/{case_id}/intelligence/analyze", status_code=202)
def case_intelligence_analyze(case_id: str, user: dict = Depends(current_user), _rl: None = Depends(rate_limited("case_intelligence", "CASE_INTELLIGENCE_PER_MIN", "CASE_INTELLIGENCE_PER_DAY", 2, 20, use_global=False))):
    # Validate ownership before returning a job id. The existing saved analysis is
    # intentionally preserved until the replacement analysis completes successfully.
    from case_workspace import assert_case
    assert_case(user["id"], case_id)
    logger.info("[CASE-INTEL] request received case=%s", case_id)
    return start_case_analysis_job(
        user["id"], case_id,
        lambda progress: analyze_once(user["id"], case_id, state["groq_client"], state.get("embed_model"), state.get("reranker"), progress=progress),
    )

@app.get("/cases/{case_id}/intelligence/status/{job_id}")
def case_intelligence_status(case_id: str, job_id: str, user: dict = Depends(current_user)):
    job = get_case_analysis_job(user["id"], case_id, job_id)
    if not job:
        raise HTTPException(404, "Analysis job not found.")
    return job

@app.post("/cases/{case_id}/analysis/{kind}")
def case_analysis(case_id: str, kind: str, user: dict = Depends(current_user)):
    return intelligence_section(user["id"], case_id, kind)

@app.get("/cases/{case_id}/issue-map")
def case_issue_map_get(case_id: str, user: dict = Depends(current_user)):
    return get_issue_map(user["id"], case_id)

@app.post("/cases/{case_id}/issue-map/build")
async def case_issue_map_build(case_id: str, user: dict = Depends(current_user), _rl: None = Depends(rate_limited("case_issue_map", "CASE_ISSUE_MAP_PER_MIN", "CASE_ISSUE_MAP_PER_DAY", 2, 20, use_global=False))):
    return await run_in_threadpool(build_issue_map, user["id"], case_id, state["groq_client"], state.get("embed_model"), state.get("reranker"), state.get("index"), state.get("records", []))

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=1000, description="The legal question to ask")
    top_k: int = Field(3, ge=1, le=10, description="Number of passages to retrieve")
    verify: bool = Field(True, description="Whether to run citation verification")
    use_graph: bool = Field(False, description="Whether to use LangGraph StateGraph Corrective RAG with citation self-correction")


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
    graph_execution: dict | None = None  # LangGraph node trace and metadata if graph mode was used


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
def root_status():
    return {"service": "LEXAI API", "status": "ok", "environment": LEXAI_ENV}


@app.get("/health")
def health():
    from rag_pipeline import _USE_GEMINI_EMBED
    embedding_mode = "gemini-embedding-001" if _USE_GEMINI_EMBED else "all-MiniLM-L6-v2"
    return {"status": "ok", "environment": LEXAI_ENV, "render_free_mode": RENDER_FREE_MODE,
            "embedding_mode": embedding_mode,
            "storage": {"persistent": bool(supabase_repo.enabled() and supabase_repo.configured()) or not RENDER_FREE_MODE, "mode": "supabase" if supabase_repo.enabled() else ("ephemeral-demo" if RENDER_FREE_MODE else "local"), "supabase": supabase_repo.health()}, "limits": {"max_upload_files": MAX_UPLOAD_FILES, "max_upload_mb": MAX_UPLOAD_MB}, "capabilities": {"global_judgment_corpus": bool(GLOBAL_CORPUS_ENABLED and state.get("index") is not None), "private_case_rag": True, "developer_tools": DEVELOPER_TOOLS_ENABLED, "cross_encoder": bool(state.get("reranker") is not None), "low_memory_mode": LOW_MEMORY_MODE, "ocr": os.getenv("OCR_ENABLED","true").lower() in {"1","true","yes","on"}}, **runtime_diagnostics(len(state.get("records", [])), provider_status())}


@app.api_route("/ping", methods=["GET", "HEAD"])
def ping():
    """Ultra-lightweight endpoint for uptime monitors and Vercel warm-up pings.
    Returns instantly without touching state, DB, or AI providers.
    Use this URL in UptimeRobot (free) to keep Render from sleeping.
    """
    return {"ok": True}


class RagRelevanceItem(BaseModel):
    judgment: str
    grade: int = Field(3, ge=0, le=3)

class RagEvalItem(BaseModel):
    query: str = Field(..., min_length=3, max_length=1600)
    relevant_files: list[str] = []
    relevant_cases: list[str] = []
    relevance: list[RagRelevanceItem] = []
    category: str | None = None
    difficulty: str | None = None
    auto_generated: bool = False
    needs_human_review: bool = False

class RagExperimentSettings(BaseModel):
    dense_candidates: int = Field(40, ge=5, le=200)
    bm25_candidates: int = Field(40, ge=5, le=200)
    rrf_candidates: int = Field(20, ge=5, le=100)
    final_k: int = Field(5, ge=1, le=20)
    rrf_k: int = Field(60, ge=1, le=200)
    rerank: bool = True

class RagEvalRequest(BaseModel):
    questions: list[RagEvalItem] = Field(..., min_length=1, max_length=200)
    top_k: int = Field(5, ge=1, le=20)
    settings: RagExperimentSettings | None = None

@app.get("/rag/inspect")
def rag_inspect(q: str = Query(..., min_length=3, max_length=1000), top_k: int = Query(5, ge=1, le=20), dense_candidates: int = Query(40, ge=5, le=200), bm25_candidates: int = Query(40, ge=5, le=200), rrf_candidates: int = Query(20, ge=5, le=100), rrf_k: int = Query(60, ge=1, le=200), rerank: bool = Query(True), user: dict = Depends(current_user)):
    _require_developer_tools()
    _require_global_corpus()
    if "index" not in state:
        raise HTTPException(status_code=503, detail="Index not loaded yet.")
    return inspect_query(q, state["index"], state["records"], state["embed_model"], state.get("reranker"), top_k, {"dense_candidates":dense_candidates,"bm25_candidates":bm25_candidates,"rrf_candidates":rrf_candidates,"final_k":top_k,"rrf_k":rrf_k,"rerank":rerank})

@app.get("/rag/benchmark/generate")
def rag_benchmark_generate(count: int = Query(100, ge=10, le=200), seed: int = Query(42, ge=0, le=999999), user: dict = Depends(current_user)):
    _require_developer_tools()
    _require_global_corpus()
    if "records" not in state:
        raise HTTPException(status_code=503, detail="Index not loaded yet.")
    return generate_benchmark(state["records"], count=count, seed=seed)

@app.get("/rag/benchmark/generate-realistic")
def rag_benchmark_generate_realistic(count: int = Query(100, ge=20, le=100), seed: int = Query(84, ge=0, le=999999), user: dict = Depends(current_user)):
    _require_developer_tools()
    _require_global_corpus()
    if "records" not in state:
        raise HTTPException(status_code=503, detail="Index not loaded yet.")
    return generate_realistic_benchmark(state["records"], count=count, seed=seed)

@app.post("/rag/evaluate")
def rag_evaluate(req: RagEvalRequest, user: dict = Depends(current_user)):
    _require_developer_tools()
    _require_global_corpus()
    if "index" not in state:
        raise HTTPException(status_code=503, detail="Index not loaded yet.")
    questions=[x.model_dump() for x in req.questions]
    return evaluate_retrieval(questions, state["index"], state["records"], state["embed_model"], state.get("reranker"), req.top_k, req.settings.model_dump() if req.settings else None)

@app.post("/rag/evaluate/jobs")
def rag_evaluate_start(req: RagEvalRequest, user: dict = Depends(current_user)):
    _require_developer_tools()
    _require_global_corpus()
    if "index" not in state:
        raise HTTPException(status_code=503, detail="Index not loaded yet.")
    questions=[x.model_dump() for x in req.questions]
    return start_benchmark_job(user["id"], questions, state["index"], state["records"], state["embed_model"], state.get("reranker"), req.top_k, req.settings.model_dump() if req.settings else None)

@app.get("/rag/evaluate/jobs/{job_id}")
def rag_evaluate_status(job_id: str, user: dict = Depends(current_user)):
    _require_developer_tools()
    _require_global_corpus()
    job=get_benchmark_job(user["id"], job_id)
    if not job: raise HTTPException(status_code=404, detail="Benchmark job not found.")
    return job

@app.post("/rag/evaluate/jobs/{job_id}/cancel")
def rag_evaluate_cancel(job_id: str, user: dict = Depends(current_user)):
    _require_developer_tools()
    _require_global_corpus()
    job=cancel_benchmark_job(user["id"], job_id)
    if not job: raise HTTPException(status_code=404, detail="Benchmark job not found.")
    return job

@app.get("/rag/evaluate/jobs/{job_id}/result")
def rag_evaluate_result(job_id: str, user: dict = Depends(current_user)):
    _require_developer_tools()
    _require_global_corpus()
    job=get_benchmark_job(user["id"], job_id)
    if not job: raise HTTPException(status_code=404, detail="Benchmark job not found.")
    if job["status"] != "completed": raise HTTPException(status_code=409, detail=f"Benchmark is {job['status']}.")
    return benchmark_job_result(user["id"], job_id)

@app.post("/query/general", response_model=QueryResponse)
def query_general(req: QueryRequest, _rl: None = Depends(rate_limited())):
    """General AI mode: deliberately bypass the indexed judgment corpus.

    This endpoint does NOT run FAISS, BM25, RRF, cross-encoder retrieval or
    corpus citation verification. The 848 indexed judgments remain untouched.
    """
    system_prompt = (
        "You are LEXAI in General AI mode. Answer the user's legal question clearly, authoritatively, and cautiously. "
        "The indexed judgment knowledge base is intentionally disabled for this request. "
        "Do not invent case citations or claim that a proposition was verified against the local corpus. "
        "Distinguish general legal information from professional legal advice and encourage checking current authoritative law when appropriate.\n\n"
        "PRESENTATION FORMAT:\n"
        "- Structure your answer cleanly with Markdown headings (## Executive Summary, ## Statutory Framework, ## Judicial Principles, ## Practical Takeaways).\n"
        "- Use bullet points for tests and essential requirements.\n"
        "- Present statutory provisions or comparative rules in a clean Markdown table (| Subject / Provision | Relevant Law | Key Principle |) whenever explaining multiple elements."
    )
    primary = call_groq(
        state.get("groq_client"), req.question, system_prompt=system_prompt,
        max_tokens=1800, temperature=0.15
    )
    result = primary
    if not result.get("ok"):
        gem = call_gemini(f"{system_prompt}\n\nUSER QUESTION:\n{req.question}", purpose="reason")
        if gem.get("ok"):
            result = gem
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail="General AI provider is temporarily unavailable. Please try again shortly.")
    return QueryResponse(
        answer=result["text"], sources=[], verification=None, not_found=False,
        statutory_fallback=True, top_score=None, threshold=None, weak_match=False, rewritten_query=None
    )


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest, _rl: None = Depends(rate_limited())):
    _require_global_corpus()

    if req.use_graph:
        from graphs.rag_graph import run_legal_rag_graph
        return run_legal_rag_graph(
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


@app.post("/query/graph", response_model=QueryResponse)
def query_graph(req: QueryRequest, _rl: None = Depends(rate_limited())):
    """Executes the Corrective Legal RAG (CRAG) workflow orchestrated via LangGraph StateGraph,
    including an Evaluator-Optimizer feedback loop for citation self-correction.
    """
    _require_global_corpus()
    from graphs.rag_graph import run_legal_rag_graph
    return run_legal_rag_graph(
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
    _require_global_corpus()

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
    sources: list[dict] = []
    correct_source: str | None = Field(None, max_length=500)
    event_type: str = Field("answer_rating", pattern="^(answer_rating|correct_source)$")


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
        sources=req.sources,
        query_type=feedback_query_type(req.question),
        correct_source=req.correct_source,
        event_type=req.event_type,
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


@app.get("/feedback/learning", dependencies=[Depends(require_admin)])
def feedback_learning(q: str = Query("general legal question", max_length=1000)):
    """Explain the bounded contextual-bandit adjustment for diagnostics."""
    return feedback_profile_adjustment(q)


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
    _require_global_corpus()
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
    _require_global_corpus()
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
            "legal_role": annotate_record(r).get("legal_role", "UNKNOWN"),
            "legal_role_confidence": r.get("legal_role_confidence", 0.0),
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
    from ocr_extraction import extract_text_and_head_with_ocr
    raw_full, raw_head, page_records, extraction_summary = extract_text_and_head_with_ocr(save_path)
    cleaned = clean_text(raw_full)
    if not cleaned:
        os.remove(save_path)
        return [], "no extractable text (scanned image?)"

    meta = extract_metadata(cleaned, filename, raw_head=raw_head)
    header = build_contextual_header(meta)
    records = []
    for i, chunk in enumerate(chunk_text(cleaned)):
        rec = {
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
            "extraction_method": extraction_summary.get("method", "native"),
            "ocr_pages": extraction_summary.get("ocr_pages", 0),
            "extraction_failed_pages": extraction_summary.get("failed_pages", []),
        }
        records.append(annotate_record(rec))
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
async def upload_files(files: list[UploadFile] = File(...), replace_existing: bool = Query(False)):
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
        if filename in saved:
            skipped.append(f"{filename}: selected more than once")
            continue
        if filename in existing and not replace_existing:
            skipped.append(f"{filename}: already indexed")
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

    # Replacement is explicit: remove old chunks only after the replacement PDF
    # has been parsed successfully, so a bad upload cannot destroy a good index.
    if replace_existing:
        replacing = {name for name in saved if name in existing}
        if replacing:
            with index_lock:
                records = state["records"]
                old_index = state["index"]
                keep_rows = [i for i, r in enumerate(records) if r.get("source_file") not in replacing]
                if keep_rows:
                    vectors = old_index.reconstruct_n(0, old_index.ntotal)
                    new_index = build_faiss_index(np.ascontiguousarray(vectors[keep_rows], dtype="float32"))
                else:
                    new_index = faiss.IndexFlatIP(old_index.d)
                new_base_records = [records[i] for i in keep_rows]
                stale_bm25 = os.path.join(INDEX_DIR, "bm25.pkl")
                if os.path.exists(stale_bm25):
                    os.remove(stale_bm25)
                save_index(new_index, new_base_records, state.get("model_name", "all-MiniLM-L6-v2"))
                state["index"], state["records"] = new_index, new_base_records

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
    if not client and not gemini_configured():
        raise HTTPException(status_code=503, detail="Configure GEMINI_API_KEY or GROQ_API_KEY")
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
    if not client and not gemini_configured():
        raise HTTPException(status_code=503, detail="Configure GEMINI_API_KEY or GROQ_API_KEY")
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
    lang: str = Field("en", description="Language for advice: 'en' (English) or 'hi' (Hindi)")


@app.post("/citizen-advice")
def get_citizen_advice(req: CitizenAdviceRequest, _rl: None = Depends(rate_limited())):
    """Analyze everyday citizen legal problems and return applicable laws, rights, and action roadmap."""
    client = state.get("groq_client")
    if not client and not gemini_configured():
        raise HTTPException(status_code=503, detail="Configure GEMINI_API_KEY or GROQ_API_KEY")
    return analyze_citizen_incident(
        incident=req.incident,
        client=client,
        index=state.get("index"),
        records=state.get("records"),
        embed_model=state.get("embed_model"),
        lang=req.lang,
    )


# ─── BNS ↔ IPC Transition Lens ──────────────────────────────────────────────

class BnsAnalyzeRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)

@app.get("/bns-lens/quick")
def bns_quick_search(q: str = Query("", max_length=200)):
    """Fast local transition search between IPC/CrPC/IEA and BNS/BNSS/BSA."""
    from bns_lens import quick_search_transition
    return {"status": "ok", "query": q, "results": quick_search_transition(q)}

@app.post("/bns-lens/analyze")
def bns_deep_analyze(req: BnsAnalyzeRequest, _rl: None = Depends(rate_limited())):
    """Deep-dive comparative analysis between old criminal law and new 2024 statutes."""
    client = state.get("groq_client")
    if not client and not gemini_configured():
        raise HTTPException(status_code=503, detail="Configure GEMINI_API_KEY or GROQ_API_KEY")
    from bns_lens import analyze_transition_with_llm
    return analyze_transition_with_llm(req.query, groq_client=client)


# ─── Scan My Notice / Contract Analyzer ─────────────────────────────────────

@app.post("/analyze-document")
async def analyze_document_upload(
    file: UploadFile = File(...),
    _rl: None = Depends(rate_limited()),
):
    """Scan and analyze an uploaded legal notice, contract, or agreement (PDF/TXT)."""
    client = state.get("groq_client")
    if not client and not gemini_configured():
        raise HTTPException(status_code=503, detail="Configure GEMINI_API_KEY or GROQ_API_KEY")

    content = await file.read()
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (limit: 15MB)")

    from document_analyzer import extract_text_from_file_bytes, analyze_legal_document
    extracted_text = extract_text_from_file_bytes(content, file.filename or "doc.pdf")
    if not extracted_text:
        raise HTTPException(status_code=400, detail="Could not extract readable text from document.")

    return analyze_legal_document(extracted_text, filename=file.filename or "notice.pdf", groq_client=client)





class CaseNoteRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1, max_length=20000)
    kind: str = Field('note', max_length=40)

class ArgumentRequest(BaseModel):
    side: str = Field(..., pattern='^(prosecution|defence|petitioner|respondent)$')
    issue: str = Field(..., min_length=3, max_length=2000)

@app.get('/cases/{case_id}/overview')
def case_overview(case_id: str, user: dict = Depends(current_user)):
    return overview(user['id'],case_id)

@app.get('/cases/{case_id}/notes')
def case_notes(case_id: str, user: dict = Depends(current_user)):
    return {'notes':list_notes(user['id'],case_id)}

@app.post('/cases/{case_id}/notes')
def case_note_add(case_id: str, req: CaseNoteRequest, user: dict = Depends(current_user)):
    return {'note':add_note(user['id'],case_id,req.title,req.content,req.kind)}

@app.delete('/cases/{case_id}/notes/{note_id}')
def case_note_delete(case_id: str, note_id: str, user: dict = Depends(current_user)):
    delete_note(user['id'],case_id,note_id); return {'ok':True}

@app.post('/cases/{case_id}/argument')
def case_argument(case_id: str, req: ArgumentRequest, user: dict = Depends(current_user), _rl: None = Depends(rate_limited('case_argument', 'CASE_ARGUMENT_PER_MIN', 'CASE_ARGUMENT_PER_DAY', 6, 80, use_global=False))):
    # build_argument calls ask_case which lazy-loads embed_model; pass None if not resident.
    # When global index is unavailable, ask_case gracefully falls back to case-only mode inside build_argument.
    return build_argument(user['id'],case_id,req.side,req.issue,state['groq_client'],state.get('embed_model'),state.get('reranker'),state.get('index'),state.get('records') or [])

@app.post('/cases/{case_id}/brief')
def case_brief(case_id: str, user: dict = Depends(current_user), _rl: None = Depends(rate_limited('case_brief', 'CASE_BRIEF_PER_MIN', 'CASE_BRIEF_PER_DAY', 4, 40, use_global=False))):
    return intelligence_brief(user['id'],case_id)

class CaseMootRequest(BaseModel):
    issue: str = Field(..., min_length=3, max_length=3000)

@app.post('/cases/{case_id}/moot-court')
def case_moot(case_id: str, req: CaseMootRequest, user: dict = Depends(current_user), _rl: None = Depends(rate_limited('case_moot', 'CASE_MOOT_PER_MIN', 'CASE_MOOT_PER_DAY', 3, 30, use_global=False))):
    # In Render free-mode the global FAISS index is None; use 'case' mode only to avoid 503.
    _mode = 'both' if state.get('index') is not None else 'case'
    grounded=ask_case(user['id'],case_id,req.issue,_mode,5,True,state.get('embed_model'),state.get('reranker'),state['groq_client'],state.get('index'),state.get('records') or [])
    context='\n'.join(f"- {s.get('scope')}: {s.get('source_file')} p.{s.get('page') or '-'}: {s.get('text','')[:450]}" for s in grounded.get('sources',[]))
    dispute=f"{req.issue}\n\nCASE-SPECIFIC VERIFIED RETRIEVAL CONTEXT:\n{context}"
    # Global moot court debate requires the corpus; skip if unavailable and return case-grounded summary only.
    if state.get('index') is None:
        return {'petitioner_argument': grounded.get('answer',''), 'respondent_argument': '', 'bench_questions': [], 'bench_verdict': 'Global corpus not available in this deployment. Case-grounded analysis returned above.', 'case_sources': grounded.get('sources', [])}
    result=run_moot_court_debate(dispute,state['index'],state['records'],state['embed_model'],state['groq_client'])
    result['case_sources']=grounded.get('sources',[]); return result


class MootCourtRequest(BaseModel):
    dispute: str = Field(..., min_length=10, max_length=4000, description="Legal proposition or case facts to debate")
    use_graph: bool = Field(True, description="Whether to orchestrate the debate via LangGraph StateGraph multi-agent workflow")


@app.post("/moot-court")
def simulate_moot_court(
    req: MootCourtRequest,
    _rl: None = Depends(rate_limited("moot", "MOOT_RATE_PER_MIN", "MOOT_RATE_PER_DAY", 6, 100, use_global=False)),
):
    """Run an adversarial moot court debate: Petitioner (Groq) vs Respondent (Groq) vs Bench (Gemini) orchestrated via LangGraph StateGraph."""
    client = state.get("groq_client")
    if not client and not gemini_configured():
        raise HTTPException(status_code=503, detail="Configure GEMINI_API_KEY or GROQ_API_KEY")
    # Global corpus required for full moot court; gracefully degrade in production if not available.
    if state.get("index") is None:
        raise HTTPException(status_code=503, detail="Moot court simulation requires the global judgment corpus, which is not enabled in this deployment. Use the Case-aware Moot Court inside a Private Case workspace instead.")
    try:
        return run_moot_court_debate(
            dispute=req.dispute,
            index=state["index"],
            records=state["records"],
            embed_model=state["embed_model"],
            groq_client=client,
            use_graph=req.use_graph,
        )
    except Exception as e:
        logger.error(f"Moot court debate failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Moot court simulation failed: {str(e)}")


@app.post("/moot-court/graph")
def simulate_moot_court_graph(
    req: MootCourtRequest,
    _rl: None = Depends(rate_limited("moot", "MOOT_RATE_PER_MIN", "MOOT_RATE_PER_DAY", 6, 100, use_global=False)),
):
    """Explicit endpoint to execute the LangGraph StateGraph multi-agent courtroom debate."""
    client = state.get("groq_client")
    if not client and not gemini_configured():
        raise HTTPException(status_code=503, detail="Configure GEMINI_API_KEY or GROQ_API_KEY")
    if state.get("index") is None:
        raise HTTPException(status_code=503, detail="Moot court simulation requires the global judgment corpus, which is not enabled in this deployment.")
    try:
        from graphs.moot_court_graph import run_moot_court_graph
        return run_moot_court_graph(
            dispute=req.dispute,
            index=state["index"],
            records=state["records"],
            embed_model=state["embed_model"],
            groq_client=client,
        )
    except Exception as e:
        logger.error(f"LangGraph Moot court execution failed: {e}", exc_info=True)
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
    if not client and not gemini_configured():
        raise HTTPException(status_code=503, detail="Configure GEMINI_API_KEY or GROQ_API_KEY")
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
    client = state.get("groq_client")
    if not client and not gemini_configured():
        raise HTTPException(status_code=503, detail="Configure GEMINI_API_KEY or GROQ_API_KEY")
    if state.get("index") is None:
        raise HTTPException(status_code=503, detail="Human vs AI moot court requires the global judgment corpus, which is not enabled in this deployment.")
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
    client = state.get("groq_client")
    if not client and not gemini_configured():
        raise HTTPException(status_code=503, detail="Configure GEMINI_API_KEY or GROQ_API_KEY")
    if state.get("index") is None:
        raise HTTPException(status_code=503, detail="Multi-turn moot court requires the global judgment corpus, which is not enabled in this deployment.")
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
