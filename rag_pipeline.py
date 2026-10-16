"""
Legal RAG Pipeline — Vertical Slice
====================================
Extraction -> Cleaning -> Chunking -> Embedding -> FAISS Indexing -> Retrieval

Run this AFTER make_sample_pdfs.py (or after dropping real judgment PDFs
into the judgments/ folder).

Requirements (install locally where you have internet access to HuggingFace):
    pip install pdfplumber faiss-cpu sentence-transformers

Usage:
    python rag_pipeline.py
"""

import os
import re
import glob
import pickle
import hashlib
from concurrent.futures import ThreadPoolExecutor

try:
    import pymupdf  # High-performance C-based PDF text extraction (10-30x faster)
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        pymupdf = None

import pdfplumber
import numpy as np
import faiss

from legal_judgment_intelligence import annotate_record, preferred_roles_for_query

from metadata_extraction import (  # noqa: E402  (see metadata_extraction.py)
    build_metadata,
    case_name_from_filename,   # re-exported for backward compatibility
    disambiguate_names,
)

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
JUDGMENTS_DIR = os.environ.get("JUDGMENTS_DIR", "judgments")
INDEX_DIR = os.environ.get("INDEX_DIR", "index_store")
CHUNK_SIZE_WORDS = 180        # approx paragraph-level chunk size
CHUNK_OVERLAP_WORDS = 40      # overlap so context isn't cut mid-idea

# Chosen after an A/B comparison against law-ai/InLegalBERT (see
# minilm_baseline.json vs inlegalbert_baseline.json from eval_pipeline.py):
# MiniLM scored higher on both Precision@3 (0.571 vs 0.286) and MRR (0.905
# vs 0.429) on this corpus. InLegalBERT is only pretrained with Masked
# Language Modeling + Next Sentence Prediction -- not a sentence-similarity
# objective -- so its raw embeddings are weaker for retrieval despite the
# legal-domain vocabulary. all-MiniLM-L6-v2 works with sentence-transformers
# directly; load_embedding_model() below is still the single place that
# decides how to load an embedding model, so swapping EMBEDDING_MODEL_NAME
# is the only change needed anywhere in the project if this is revisited.
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"


def load_embedding_model(model_name: str = EMBEDDING_MODEL_NAME):
    """Single place that decides HOW to load an embedding model, so
    swapping EMBEDDING_MODEL_NAME is the only change needed anywhere in
    the project -- rag_pipeline.py, main.py, generate_answer.py, and
    eval_pipeline.py should all call this instead of instantiating
    SentenceTransformer directly.
    """
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(model_name)


# ---------------------------------------------------------------------------
# STEP 1: PDF EXTRACTION (Fast PyMuPDF with single-pass head + fallback)
# ---------------------------------------------------------------------------
def extract_text_and_head(pdf_path: str, head_pages: int = 2) -> tuple[str, str]:
    """Extract raw full text and the first `head_pages` text in a single pass.
    Prefers pymupdf for 10-30x speedup with graceful fallback to pdfplumber.
    Eliminates redundant file I/O.
    """
    # Shared page-level OCR fallback. Native extraction remains preferred.
    try:
        from ocr_extraction import extract_text_and_head_with_ocr
        full, head, _pages, _summary = extract_text_and_head_with_ocr(pdf_path, head_pages)
        if full:
            return full, head
    except Exception:
        pass

    full_text = []
    head_text = []

    if pymupdf is not None:
        try:
            with pymupdf.open(pdf_path) as doc:
                for idx, page in enumerate(doc):
                    t = page.get_text() or ""
                    if t:
                        full_text.append(t)
                    if idx < head_pages and t:
                        head_text.append(t)
            return "\n".join(full_text), "\n".join(head_text)
        except Exception:
            pass  # Fall back to pdfplumber on corrupt or unsupported file

    try:
        with pdfplumber.open(pdf_path) as pdf:
            for idx, page in enumerate(pdf.pages):
                t = page.extract_text() or ""
                if t:
                    full_text.append(t)
                if idx < head_pages and t:
                    head_text.append(t)
        return "\n".join(full_text), "\n".join(head_text)
    except Exception:
        return "", ""


def extract_text_from_pdf(pdf_path: str) -> str:
    """Extract raw text from a judgment PDF, page by page."""
    full_text, _ = extract_text_and_head(pdf_path)
    return full_text


# ---------------------------------------------------------------------------
# STEP 2: CLEANING
# ---------------------------------------------------------------------------
def clean_text(text: str) -> str:
    """Basic cleanup: collapse whitespace, drop page-number-only lines."""
    lines = text.split("\n")
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # drop lines that are just numbers (common page-number artifacts)
        if re.fullmatch(r"\d+", stripped):
            continue
        cleaned_lines.append(stripped)
    text = " ".join(cleaned_lines)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# STEP 3: METADATA EXTRACTION (very light heuristic version)
# ---------------------------------------------------------------------------
def read_raw_head(pdf_path: str, pages: int = 2) -> str:
    """First `pages` pages of a PDF WITH line breaks intact. The SCR header
    parser needs the line structure ('v.' on its own line) that clean_text()
    deliberately flattens."""
    _, head_text = extract_text_and_head(pdf_path, head_pages=pages)
    return head_text


def extract_metadata(text: str, filename: str, raw_head: str = "") -> dict:
    """Pull out case name / court / case number (see metadata_extraction.py
    for the parsing rules and the two PDF layouts they handle). `raw_head`
    is optional for backward compatibility; without it only the
    filename + flattened-text heuristics are available."""
    return build_metadata(filename, raw_head=raw_head, cleaned_text=text)


# ---------------------------------------------------------------------------
# STEP 4: CHUNKING (word-based sliding window + contextual metadata header)
# ---------------------------------------------------------------------------
def build_contextual_header(meta: dict) -> str:
    """Build a concise metadata header to prepend to chunk text.
    Anchors each chunk to its case identity, court, and citation so both
    dense embedding models and lexical BM25 match case-specific queries
    even if the chunk text itself does not repeat the party names.
    """
    parts = []
    if meta.get("case_name"):
        parts.append(f"Case: {meta['case_name']}")
    if meta.get("court"):
        parts.append(f"Court: {meta['court']}")
    if meta.get("case_no"):
        parts.append(f"Case No: {meta['case_no']}")
    if meta.get("neutral_citation"):
        parts.append(f"Citation: {meta['neutral_citation']}")
    if not parts:
        return ""
    return "[" + " | ".join(parts) + "]"


def chunk_text(text: str, chunk_size=CHUNK_SIZE_WORDS, overlap=CHUNK_OVERLAP_WORDS):
    """Split cleaned text into overlapping word-count chunks."""
    words = text.split()
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk_words = words[start:end]
        chunks.append(" ".join(chunk_words))
        if end >= len(words):
            break
        start = end - overlap
    return chunks


# ---------------------------------------------------------------------------
# STEP 5: BUILD CORPUS (extract -> clean -> chunk for every PDF)
def _process_single_pdf_worker(pdf_path: str):
    """Worker function to read, clean, and extract head in parallel."""
    filename = os.path.basename(pdf_path)
    raw_full, raw_head = extract_text_and_head(pdf_path)
    cleaned = clean_text(raw_full)
    return pdf_path, filename, cleaned, raw_head


# ---------------------------------------------------------------------------
# STEP 5: BUILD CORPUS (extract -> clean -> chunk for every PDF)
# ---------------------------------------------------------------------------
def build_corpus(judgments_dir: str, max_workers: int = None):
    """Returns a list of chunk records:
    {chunk_id, text, case_name, court, case_no, source_file}

    Exact-duplicate PDFs (same cleaned text under a different filename, e.g.
    'X.pdf' and 'X_dup2.pdf') are detected by content hash and indexed only
    once -- otherwise both copies surface as separate "sources" for the same
    passage and the per-document cap can't dedupe them.
    """
    pdf_paths = sorted(set(
        glob.glob(os.path.join(judgments_dir, "*.pdf"))
        + glob.glob(os.path.join(judgments_dir, "*.PDF"))
    ))

    if not pdf_paths:
        raise FileNotFoundError(
            f"No PDFs found in '{judgments_dir}/'. Run make_sample_pdfs.py "
            f"first, or drop real judgment PDFs into that folder."
        )

    if max_workers is None:
        max_workers = min(16, (os.cpu_count() or 1) * 2)

    # Parallel text extraction + cleaning using thread pool (PyMuPDF releases GIL)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        extracted_docs = list(executor.map(_process_single_pdf_worker, pdf_paths))

    docs, seen_hashes, skipped = [], {}, []
    for pdf_path, filename, cleaned, raw_head in extracted_docs:
        if cleaned:  # never hash-dedupe empty (scanned) docs -- they'd all collide
            digest = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
            if digest in seen_hashes:
                skipped.append((filename, seen_hashes[digest]))
                continue
            seen_hashes[digest] = filename

        meta = extract_metadata(cleaned, filename, raw_head=raw_head)
        docs.append((filename, cleaned, meta))

    # disambiguate_names mutates the meta dicts in-place (appends a tag to
    # case_name when two documents share the same name) and returns the count
    # of names changed. The docs list still holds references to the same dicts,
    # so the updated case_name is visible when we iterate docs below.
    renamed = disambiguate_names([m for _, _, m in docs])

    records = []
    for filename, cleaned, meta in docs:
        header = build_contextual_header(meta)
        for i, chunk in enumerate(chunk_text(cleaned)):
            enriched_text = f"{header}\n{chunk}" if header else chunk
            rec = {
                "chunk_id": f"{filename}::chunk{i}",
                "text": enriched_text,
                "raw_text": chunk,
                "case_name": meta["case_name"],
                "court": meta["court"],
                "case_no": meta["case_no"],
                "neutral_citation": meta.get("neutral_citation"),
                "decision_date": meta.get("decision_date"),
                "bench": meta.get("bench"),
                "scr_citation": meta.get("scr_citation"),
                "source_file": filename,
            }
            records.append(annotate_record(rec))

    for dup, orig in skipped:
        print(f"  skipped duplicate: {dup}  (identical to {orig})")
    if renamed:
        print(f"  disambiguated {renamed} case names that collided")
    print(f"Processed {len(docs)} unique PDFs ({len(skipped)} duplicates skipped) "
          f"-> {len(records)} chunks")
    return records


# ---------------------------------------------------------------------------
# STEP 6: EMBEDDING
# ---------------------------------------------------------------------------
def embed_chunks(records, model_name=EMBEDDING_MODEL_NAME, batch_size: int = 128):
    """Embed every chunk's text.
    NOTE: requires internet access to download the model from HuggingFace
    the first time it's run.
    """
    model = load_embedding_model(model_name)
    texts = [r["text"] for r in records]
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=True,  # so we can use cosine similarity via inner product
    )
    return np.asarray(embeddings).astype("float32"), model


# ---------------------------------------------------------------------------
# STEP 7: FAISS INDEX
# ---------------------------------------------------------------------------
def build_faiss_index(embeddings: np.ndarray):
    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)  # inner product == cosine sim (since normalized)
    index.add(embeddings)
    return index


def save_index(index, records, model_name, out_dir=INDEX_DIR):
    os.makedirs(out_dir, exist_ok=True)
    faiss.write_index(index, os.path.join(out_dir, "faiss.index"))
    with open(os.path.join(out_dir, "records.pkl"), "wb") as f:
        pickle.dump({"records": records, "model_name": model_name}, f)

    # Precompute and save BM25 index for fast hybrid search startup
    try:
        build_or_load_bm25(records, index_dir=out_dir)
    except Exception as e:
        print(f"  Note: BM25 index save skipped ({e})")

    print(f"Saved index + {len(records)} chunk records to '{out_dir}/'")


def load_index(out_dir=INDEX_DIR):
    index = faiss.read_index(os.path.join(out_dir, "faiss.index"))
    with open(os.path.join(out_dir, "records.pkl"), "rb") as f:
        data = pickle.load(f)
    return index, data["records"], data["model_name"]


# ---------------------------------------------------------------------------
# STEP 7.5: BM25 LEXICAL INDEX & TOKENIZATION (with zero-dependency fallback)
# ---------------------------------------------------------------------------
class _PurePythonBM25Okapi:
    """Inverted-index BM25Okapi implementation for environments where rank-bm25
    is not yet installed. Computes exact Okapi BM25 scores in pure Python/NumPy.

    Kept as a SEPARATELY-NAMED class (rather than redefining `BM25Okapi`
    directly inside the except block) purely so static type checkers like
    Pylance don't see two conflicting declarations of the same name and
    complain that rank_bm25's real BM25Okapi "is not assignable to" this
    one -- that warning was a type-checker artifact of the old pattern,
    not a real bug, but this avoids it entirely. BM25Okapi is bound to
    whichever implementation is available via the single assignment
    below, so everything else in this file that imports/uses BM25Okapi
    is completely unaffected.
    """
    def __init__(self, corpus: list, k1: float = 1.5, b: float = 0.75):
        import math
        from collections import Counter

        self.k1 = k1
        self.b = b
        self.corpus_size = len(corpus)
        self.doc_lens = np.array([len(d) for d in corpus], dtype=np.float32)
        self.avgdl = float(np.mean(self.doc_lens)) if len(self.doc_lens) > 0 else 1.0
        self.inverted = {}
        for doc_id, doc in enumerate(corpus):
            for term, count in Counter(doc).items():
                if term not in self.inverted:
                    self.inverted[term] = []
                self.inverted[term].append((doc_id, count))
        self.idf = {
            term: math.log((self.corpus_size - len(postings) + 0.5) / (len(postings) + 0.5) + 1.0)
            for term, postings in self.inverted.items()
        }

    def get_scores(self, query: list) -> np.ndarray:
        scores = np.zeros(self.corpus_size, dtype=np.float32)
        for term in query:
            if term not in self.inverted:
                continue
            q_idf = self.idf[term]
            for doc_id, tf in self.inverted[term]:
                denom = tf + self.k1 * (1.0 - self.b + self.b * (self.doc_lens[doc_id] / self.avgdl))
                scores[doc_id] += q_idf * (tf * (self.k1 + 1.0)) / denom
        return scores


try:
    from rank_bm25 import BM25Okapi
except ImportError:
    BM25Okapi = _PurePythonBM25Okapi


def tokenize_for_bm25(text: str) -> list[str]:
    """Tokenize legal text for BM25: lowercased alphanumeric tokens,
    preserving numbers and statute sections (e.g. '138', '41')."""
    return re.findall(r"\w+", text.lower())


_BM25_CACHE = {}


def build_or_load_bm25(records: list, index_dir: str = INDEX_DIR):
    """Retrieve or build a BM25Okapi index over records.
    Cached in-memory and persisted on disk as bm25.pkl in index_dir for fast startup.
    """
    cache_key = (id(records), len(records))
    if cache_key in _BM25_CACHE:
        return _BM25_CACHE[cache_key]

    bm25_path = os.path.join(index_dir, "bm25.pkl")
    if os.path.exists(bm25_path):
        try:
            with open(bm25_path, "rb") as f:
                data = pickle.load(f)
                if isinstance(data, dict) and data.get("n_records") == len(records):
                    bm25 = data["bm25"]
                    _BM25_CACHE.clear()          # keep only the current index's BM25
                    _BM25_CACHE[cache_key] = bm25
                    return bm25
        except Exception:
            pass

    tokenized = []
    for r in records:
        text = r.get("text", "")
        # If record text does not already have contextual header, enrich tokenization
        # with metadata so BM25 matches case names, courts, and case numbers.
        if "Case:" not in text and r.get("case_name"):
            meta_str = f"{r.get('case_name', '')} {r.get('court', '')} {r.get('case_no', '')} {r.get('neutral_citation', '')}"
            text = f"{meta_str} {text}"
        tokenized.append(tokenize_for_bm25(text))

    bm25 = BM25Okapi(tokenized)
    # Only ever keep ONE entry: after each upload/delete the old BM25 (hundreds
    # of MB at 60k chunks) would otherwise stay cached forever, and a recycled
    # id(records) could even return a stale index for a different record list.
    _BM25_CACHE.clear()
    _BM25_CACHE[cache_key] = bm25

    if os.path.exists(index_dir):
        try:
            with open(bm25_path, "wb") as f:
                pickle.dump({"bm25": bm25, "n_records": len(records)}, f)
        except Exception:
            pass

    return bm25


# ---------------------------------------------------------------------------
# STEP 7.8: CROSS-ENCODER RE-RANKER
# ---------------------------------------------------------------------------
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
_RERANKER_CACHE = {}


def load_reranker_model(model_name: str = RERANKER_MODEL_NAME):
    """Load and cache the Cross-Encoder re-ranking model."""
    if model_name in _RERANKER_CACHE:
        return _RERANKER_CACHE[model_name]
    try:
        from sentence_transformers import CrossEncoder
        model = CrossEncoder(model_name)
        _RERANKER_CACHE[model_name] = model
        return model
    except Exception as e:
        print(f"  Note: CrossEncoder could not be loaded ({e})")
        return None


# ---------------------------------------------------------------------------
def _normalize_legal_text(query: str) -> str:
    """Normalize OCR/citation noise without changing the user's displayed query."""
    q = (query or "").replace("§", " Section ")
    q = re.sub(r"(?i)\bsec(?:tion)?\.?\s*", "Section ", q)
    q = re.sub(r"(?i)(?<![A-Za-z])s\.\s*(?=\d|\()", "Section ", q)
    q = re.sub(r"(?i)\bart\.?\s*", "Article ", q)
    q = re.sub(r"([A-Za-z])\-\s+([A-Za-z])", r"\1\2", q)  # OCR line-break hyphenation
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _extract_sections(normalized: str):
    vals = re.findall(r"(?i)\bSection\s*([0-9]+[A-Za-z]?(?:\s*\([^)]*\))?)", normalized)
    # subsection-only forms such as "section (1-A)" are legally incomplete but important.
    vals += [f"({x.strip()})" for x in re.findall(r"(?i)\bSection\s*\(([^)]+)\)", normalized)]
    out=[]
    for x in vals:
        x=re.sub(r"\s+", " ", x).strip()
        if x not in out: out.append(x)
    return out


def _resolve_acts(normalized: str):
    """Canonical statute resolver with abbreviations, historical names and conservative OCR tolerance."""
    low=normalized.lower()
    patterns=[
      (r"negotiable\s+instruments?|\bni\s+act\b", "Negotiable Instruments Act"),
      (r"code\s+of\s+criminal\s+procedure|\bcr\.?p\.?c\.?\b", "Code of Criminal Procedure"),
      (r"indian\s+penal\s+code|\bi\.?p\.?c\.?\b", "Indian Penal Code"),
      (r"bharatiya\s+nagarik\s+suraksha\s+sanhita|\bbnss\b", "Bharatiya Nagarik Suraksha Sanhita"),
      (r"bharatiya\s+nyaya\s+sanhita|\bbns\b", "Bharatiya Nyaya Sanhita"),
      (r"indian\s+evidence\s+act|\bevidence\s+act\b", "Indian Evidence Act"),
      (r"workmen.?s\s+compensation\s+act|employees.?\s+compensation\s+act", "Employees Compensation Act"),
      (r"constitution\s+of\s+india|\bconstitution\b", "Constitution of India"),
      (r"probation\s+of\s+(?:the\s+)?offenders\s+act", "Probation of Offenders Act"),
      (r"employees.?\s+state\s+insurance\s+act|\besi\s+act\b", "Employees State Insurance Act"),
      (r"employees.?\s+provident\s+funds?.{0,30}miscellaneous\s+provisions\s+act|\bepf\s+act\b", "Employees Provident Funds and Miscellaneous Provisions Act"),
    ]
    acts=[]
    for pat,name in patterns:
        if re.search(pat,low,re.I) and name not in acts: acts.append(name)
    # OCR-tolerant aliases observed in old judgments. Keep thresholds conservative.
    if not acts:
        compact=re.sub(r"[^a-z]", "", low)
        if "workmen" in compact and ("compensa" in compact or "cpmpensa" in compact):
            acts.append("Employees Compensation Act")
        elif "employee" in compact and "stateinsurance" in compact:
            acts.append("Employees State Insurance Act")
    return acts


def analyze_legal_query(query: str):
    """Local deterministic legal-query intelligence. No LLM/API calls."""
    q=(query or '').strip(); normalized=_normalize_legal_text(q); low=normalized.lower()
    sections=_extract_sections(normalized)
    articles=[]
    for x in re.findall(r'(?i)\bArticle\s*([0-9]+[a-z]?(?:\s*\([^)]*\))?)', normalized):
        x=re.sub(r'\s+',' ',x).strip()
        if x not in articles: articles.append(x)
    acts=_resolve_acts(normalized)
    case_names=[]
    m=re.search(r'([A-Z][A-Za-z0-9 .&/-]{2,80})\s+(?:v\.?|vs\.?|versus)\s+([A-Z][A-Za-z0-9 .&/-]{2,80})', q)
    if m: case_names.append((m.group(1).strip()+' vs '+m.group(2).strip())[:160])
    courts=[]
    for pat,name in [(r'supreme court','Supreme Court'),(r'high court','High Court'),(r'trial court','Trial Court'),(r'district court','District Court')]:
        if re.search(pat,low): courts.append(name)
    kind=classify_legal_query(normalized)
    subsection_only=any(x.startswith('(') for x in sections)
    ambiguous=bool((sections and not acts) or subsection_only)
    reasons=[]
    if sections and not acts: reasons.append('A section/subsection is present but the governing Act/statute is not identified.')
    if subsection_only: reasons.append('Only a subsection is identified; the parent section is missing.')
    if len(normalized.split()) < 5 and (sections or articles): reasons.append('The statutory query is very short and may match many unrelated authorities.')
    return {'query_type':kind,'sections':sections,'articles':articles,'acts':acts,'case_names':case_names,'courts':courts,
            'ambiguous':ambiguous,'ambiguity_reasons':list(dict.fromkeys(reasons)),'complete':not ambiguous,
            'normalized_query':normalized}


def classify_legal_query(query: str) -> str:
    """Cheap local router: no LLM/API call."""
    q=_normalize_legal_text(query).lower()
    if re.search(r'\b(v\.?|vs\.?|versus)\b|\b\d{4}\s*(scc|air|scr)\b', q): return 'case_citation'
    if re.search(r'\b(section|article)\s*(?:\d|\()', q) or re.search(r'\b(ipc|crpc|bnss|bns|evidence act|negotiable instruments|constitution)\b',q): return 'statutory'
    if re.search(r'\b(precedent|authority|rely on|argu(?:e|ing)|case law|support my case)\b',q): return 'advocate'
    if re.search(r'\b(why|whether|when can|can a|principle|meaning|interpret|legal issue)\b',q): return 'semantic'
    return 'mixed'


def enrich_legal_query(query: str) -> str:
    """Deterministic canonical legal aliases for sparse retrieval; no API calls."""
    q=query or ''; analysis=analyze_legal_query(q); normalized=analysis['normalized_query']; low=normalized.lower(); extra=[]
    canon={
      'Negotiable Instruments Act':'Negotiable Instruments Act NI Act cheque dishonour legally enforceable debt statutory notice',
      'Code of Criminal Procedure':'Code of Criminal Procedure CrPC criminal procedure Magistrate',
      'Indian Penal Code':'Indian Penal Code IPC offence punishment',
      'Bharatiya Nagarik Suraksha Sanhita':'Bharatiya Nagarik Suraksha Sanhita BNSS criminal procedure',
      'Bharatiya Nyaya Sanhita':'Bharatiya Nyaya Sanhita BNS offence punishment',
      'Indian Evidence Act':'Indian Evidence Act evidence proof admissibility',
      'Employees Compensation Act':'Workmens Compensation Act Workmen Compensation Act Employees Compensation Act compensation appeal',
      'Constitution of India':'Constitution of India constitutional jurisdiction',
      'Probation of Offenders Act':'Probation of Offenders Act probation conviction',
      'Employees State Insurance Act':'Employees State Insurance Act ESI Act contribution employer',
      'Employees Provident Funds and Miscellaneous Provisions Act':'Employees Provident Funds and Miscellaneous Provisions Act EPF Act provident fund',
    }
    for act in analysis['acts']: extra.append(canon.get(act,act))
    if re.search(r'\bArticle\s*226\b', normalized,re.I): extra.append('Article 226 writ jurisdiction High Court Constitution of India')
    if re.search(r'\bSection\s*138\b', normalized,re.I): extra.append('Section 138 cheque dishonour legally enforceable debt statutory notice')
    if re.search(r'\bSection\s*482\b', normalized,re.I): extra.append('Section 482 inherent powers High Court quashing proceedings')
    if 'Code of Criminal Procedure' in analysis['acts'] and re.search(r'\bSection\s*164\b', normalized,re.I): extra.append('Section 164 CrPC Magistrate statement confession recording')
    return (q+' '+' '.join(dict.fromkeys(extra))).strip()

def adaptive_retrieval_profile(query: str):
    analysis=analyze_legal_query(query); kind=analysis['query_type']
    profiles={'statutory':(0.85,1.55,0.42),'case_citation':(0.55,1.85,0.50),'semantic':(1.35,0.95,0.22),'advocate':(1.15,1.25,0.30),'mixed':(1.0,1.25,0.30)}
    dw,bw,st=profiles[kind]
    return {'query_type':kind,'dense_weight':dw,'bm25_weight':bw,'rerank_stability':st,'query_analysis':analysis,'enriched_query':enrich_legal_query(query)}

# STEP 8: RETRIEVAL (Hybrid: Dense FAISS + Sparse BM25 via RRF + Optional Re-ranking)
# ---------------------------------------------------------------------------
def search(
    query: str,
    index,
    records,
    model,
    top_k: int = 3,
    max_per_doc: int = 2,
    hybrid: bool = True,
    dense_weight: float = 1.0,
    bm25_weight: float = 0.35,
    rrf_k: int = 60,
    candidate_pool_size: int = 100,
    rerank: bool = False,
    reranker_model = None,
    rerank_pool_size: int = 15,
    bm25_index_dir: str = INDEX_DIR,
    retrieval_strategy: str = None,
    bm25_rescue_docs: int = None,
    rerank_stability: float = None,
):
    """Retrieve the top_k most relevant chunks for a query.

    When hybrid=True (default), performs Hybrid Search combining Dense FAISS
    and Sparse BM25 retrieval via Reciprocal Rank Fusion (RRF).
    When rerank=True, runs a Cross-Encoder over the top candidate pool to
    score token-level query-passage alignment.
    Preserves calibrated cosine similarity scores so refusal guardrails
    (MIN_RETRIEVAL_SCORE) work accurately.

    max_per_doc caps how many chunks from the SAME source_file can occupy
    the result set (default 2).
    """
    # Retrieval quality controls. `legacy` reproduces the previous behavior.
    # `improved` preserves strong sparse authorities in the reranker pool and
    # blends reranker evidence with fusion rank for stability.
    retrieval_strategy = (retrieval_strategy or os.getenv("RAG_RETRIEVAL_STRATEGY", "adaptive")).strip().lower()
    if retrieval_strategy not in {"legacy", "improved", "adaptive"}:
        retrieval_strategy = "improved"
    if bm25_rescue_docs is None:
        bm25_rescue_docs = int(os.getenv("RAG_BM25_RESCUE_DOCS", "5"))
    if rerank_stability is None:
        rerank_stability = float(os.getenv("RAG_RERANK_STABILITY", "0.25"))
    bm25_rescue_docs = max(0, min(int(bm25_rescue_docs), 20))
    rerank_stability = max(0.0, min(float(rerank_stability), 0.75))
    adaptive_profile = adaptive_retrieval_profile(query) if retrieval_strategy == "adaptive" else None
    if adaptive_profile:
        dense_weight = adaptive_profile["dense_weight"]
        bm25_weight = adaptive_profile["bm25_weight"]
        rerank_stability = adaptive_profile["rerank_stability"]

    query_vec = np.asarray(
        model.encode([query], normalize_embeddings=True, convert_to_numpy=True)
    ).astype("float32")

    fetch_k = len(records)
    dense_scores_all, dense_indices_all = index.search(query_vec, fetch_k)

    if not hybrid:
        results = []
        doc_counts = {}
        for score, idx in zip(dense_scores_all[0], dense_indices_all[0]):
            if idx == -1:
                continue
            record = records[idx]
            if max_per_doc is not None:
                count = doc_counts.get(record["source_file"], 0)
                if count >= max_per_doc:
                    continue
                doc_counts[record["source_file"]] = count + 1

            results.append({
                "score": float(score),
                "case_name": record["case_name"],
                "case_no": record["case_no"],
                "source_file": record["source_file"],
                "text": record["text"],
                "raw_text": record.get("raw_text", record["text"]),
            })
            if len(results) >= top_k:
                break
        return results

    # --- Hybrid Search via Reciprocal Rank Fusion (RRF) ---
    # 1. Dense candidate ranking
    dense_rank = {}
    dense_score_map = {}
    dense_candidates_k = min(candidate_pool_size, len(records))
    for rank_idx in range(dense_candidates_k):
        idx = int(dense_indices_all[0][rank_idx])
        if idx == -1:
            continue
        dense_rank[idx] = rank_idx + 1  # 1-based rank
        dense_score_map[idx] = float(dense_scores_all[0][rank_idx])

    # Keep dense score map for all indices in case BM25 brings in a chunk outside dense top-K
    for rank_idx, idx in enumerate(dense_indices_all[0]):
        if idx != -1 and idx not in dense_score_map:
            dense_score_map[idx] = float(dense_scores_all[0][rank_idx])

    # 2. BM25 candidate ranking
    bm25 = build_or_load_bm25(records, index_dir=bm25_index_dir)
    sparse_query = enrich_legal_query(query) if retrieval_strategy == "adaptive" else query
    query_tokens = tokenize_for_bm25(sparse_query)
    bm25_scores = bm25.get_scores(query_tokens)

    bm25_rank = {}
    positive_bm25_indices = np.where(bm25_scores > 0)[0]
    if len(positive_bm25_indices) > 0:
        sorted_bm25_pos = positive_bm25_indices[np.argsort(bm25_scores[positive_bm25_indices])[::-1]]
        for r_idx, idx in enumerate(sorted_bm25_pos[:candidate_pool_size]):
            bm25_rank[int(idx)] = r_idx + 1

    # 3. Fuse with Reciprocal Rank Fusion (RRF)
    all_candidate_indices = set(dense_rank.keys()) | set(bm25_rank.keys())
    rrf_scores = {}
    for idx in all_candidate_indices:
        rrf_val = 0.0
        if idx in dense_rank:
            rrf_val += dense_weight / (rrf_k + dense_rank[idx])
        if idx in bm25_rank:
            rrf_val += bm25_weight / (rrf_k + bm25_rank[idx])
        rrf_scores[idx] = rrf_val

    # Sort candidates by fused RRF score descending
    sorted_candidates = sorted(rrf_scores.keys(), key=lambda i: rrf_scores[i], reverse=True)

    # Optional Re-ranking stage (Cross-Encoder). Improved mode protects a
    # handful of the strongest BM25 *documents* from being pruned before the
    # reranker sees them. They are candidates only -- not forced final hits.
    rerank_scores_map = {}
    final_score_map = {}
    if rerank:
        top_pool = list(sorted_candidates[:rerank_pool_size])
        if retrieval_strategy in {"improved", "adaptive"} and bm25_rescue_docs > 0:
            rescued_docs = set()
            for idx, _rank in sorted(bm25_rank.items(), key=lambda x: x[1]):
                doc = records[idx].get("source_file") or records[idx].get("case_name") or str(idx)
                if doc in rescued_docs:
                    continue
                rescued_docs.add(doc)
                if idx not in top_pool:
                    top_pool.append(idx)
                if len(rescued_docs) >= bm25_rescue_docs:
                    break
        if reranker_model is None:
            reranker_model = load_reranker_model()
        if reranker_model is not None and top_pool:
            pairs = [[query, records[idx]["text"]] for idx in top_pool]
            try:
                raw = np.asarray(reranker_model.predict(pairs), dtype=float)
                for p_idx, score_val in zip(top_pool, raw):
                    rerank_scores_map[p_idx] = float(score_val)
                if retrieval_strategy in {"improved", "adaptive"} and len(top_pool) > 1:
                    # Min-max normalize reranker and RRF signals before blending.
                    rmin, rmax = float(raw.min()), float(raw.max())
                    rnorm = (raw-rmin)/(rmax-rmin) if rmax > rmin else np.ones_like(raw)
                    fvals = np.asarray([rrf_scores.get(i, 0.0) for i in top_pool], dtype=float)
                    fmin, fmax = float(fvals.min()), float(fvals.max())
                    fnorm = (fvals-fmin)/(fmax-fmin) if fmax > fmin else np.ones_like(fvals)
                    blended = (1.0-rerank_stability)*rnorm + rerank_stability*fnorm
                    final_score_map = {i: float(v) for i, v in zip(top_pool, blended)}
                    ranked_pool = sorted(top_pool, key=lambda i: final_score_map[i], reverse=True)
                    if retrieval_strategy == "adaptive":
                        # Protect candidates independently supported by both retrievers.
                        protected=[i for i in top_pool if dense_rank.get(i,999)>0 and dense_rank.get(i,999)<=3 and bm25_rank.get(i,999)<=3]
                        for i in protected:
                            pos=ranked_pool.index(i)
                            max_pos=2  # zero-based: cannot fall below rank 3
                            if pos>max_pos:
                                ranked_pool.pop(pos); ranked_pool.insert(max_pos,i)
                else:
                    ranked_pool = [top_pool[i] for i in np.argsort(raw)[::-1]]
                tail = [i for i in sorted_candidates if i not in set(top_pool)]
                sorted_candidates = ranked_pool + tail
            except Exception as e:
                print(f"  Note: Re-ranking pass failed, falling back to RRF ({e})")

    # V4.3 legal-aware metadata. Existing indexes remain valid: old records are
    # classified lazily, while newly ingested chunks are classified at ingestion.
    preferred_roles = preferred_roles_for_query(query)
    for _idx in sorted_candidates:
        annotate_record(records[_idx])
    if preferred_roles:
        # Conservative role awareness: a matching legal role may move at most
        # two positions upward. Relevance remains controlled by Adaptive V4.1.
        ranked = list(sorted_candidates)
        for pos in range(1, len(ranked)):
            idx = ranked[pos]
            if records[idx].get("legal_role") in preferred_roles:
                target = max(0, pos - 2)
                ranked.pop(pos)
                ranked.insert(target, idx)
        sorted_candidates = ranked

    # 4. Greedy selection respecting max_per_doc
    results = []
    doc_counts = {}
    for idx in sorted_candidates:
        record = records[idx]
        source_file = record["source_file"]
        if max_per_doc is not None:
            count = doc_counts.get(source_file, 0)
            if count >= max_per_doc:
                continue
            doc_counts[source_file] = count + 1

        d_score = dense_score_map.get(idx, 0.0)
        b_score = float(bm25_scores[idx]) if 0 <= idx < len(bm25_scores) else 0.0
        r_item = {
            "score": d_score,
            "rrf_score": rrf_scores[idx],
            "dense_score": d_score,
            "bm25_score": b_score,
            "case_name": record["case_name"],
            "case_no": record["case_no"],
            "source_file": record["source_file"],
            "text": record["text"],
            "raw_text": record.get("raw_text", record["text"]),
            "legal_role": record.get("legal_role", "UNKNOWN"),
            "legal_role_confidence": record.get("legal_role_confidence", 0.0),
            "legal_role_preferred": record.get("legal_role") in preferred_roles if preferred_roles else False,
        }
        if idx in rerank_scores_map:
            r_item["rerank_score"] = rerank_scores_map[idx]
        if idx in final_score_map:
            r_item["final_rank_score"] = final_score_map[idx]
        r_item["retrieval_strategy"] = retrieval_strategy
        if adaptive_profile:
            r_item["query_type"] = adaptive_profile["query_type"]
            r_item["adaptive_profile"] = adaptive_profile
            r_item["retrieval_agreement"] = int(dense_rank.get(idx,999)<=3) + int(bm25_rank.get(idx,999)<=3)
        results.append(r_item)
        if len(results) >= top_k:
            break

    # If top_k is still under-filled (e.g. if one giant document dominated the RRF pool
    # and hit max_per_doc), continue scanning the full dense index to ensure exactly top_k results.
    if len(results) < top_k:
        for idx in dense_indices_all[0]:
            idx = int(idx)
            if idx == -1:
                continue
            record = records[idx]
            source_file = record["source_file"]
            if max_per_doc is not None:
                count = doc_counts.get(source_file, 0)
                if count >= max_per_doc:
                    continue
                doc_counts[source_file] = count + 1

            d_score = dense_score_map.get(idx, 0.0)
            b_score = float(bm25_scores[idx]) if 0 <= idx < len(bm25_scores) else 0.0
            r_item = {
                "score": d_score,
                "rrf_score": rrf_scores.get(idx, 0.0),
                "dense_score": d_score,
                "bm25_score": b_score,
                "case_name": record["case_name"],
                "case_no": record["case_no"],
                "source_file": record["source_file"],
                "text": record["text"],
                "raw_text": record.get("raw_text", record["text"]),
            }
            if idx in rerank_scores_map:
                r_item["rerank_score"] = rerank_scores_map[idx]
            if idx in final_score_map:
                r_item["final_rank_score"] = final_score_map[idx]
            r_item["retrieval_strategy"] = retrieval_strategy
            if adaptive_profile:
                r_item["query_type"] = adaptive_profile["query_type"]
                r_item["adaptive_profile"] = adaptive_profile
                r_item["retrieval_agreement"] = int(dense_rank.get(idx,999)<=3) + int(bm25_rank.get(idx,999)<=3)
            results.append(r_item)
            if len(results) >= top_k:
                break

    return results


def pretty_print_results(query, results):
    print(f"\n{'='*70}\nQUERY: {query}\n{'='*70}")
    for rank, r in enumerate(results, 1):
        extra_parts = []
        if 'rrf_score' in r:
            extra_parts.append(f"RRF={r['rrf_score']:.4f}")
        if 'bm25_score' in r:
            extra_parts.append(f"BM25={r.get('bm25_score', 0):.2f}")
        if 'rerank_score' in r:
            extra_parts.append(f"ReRank={r['rerank_score']:.4f}")
        extra = f"  ({', '.join(extra_parts)})" if extra_parts else ''
        print(f"\n[{rank}] score={r['score']:.4f}{extra}  |  {r['case_name']}  ({r['source_file']})")
        snippet = r["text"][:280] + ("..." if len(r["text"]) > 280 else "")
        print(f"    {snippet}")


# ---------------------------------------------------------------------------
# MAIN — build index once, then run a few test queries
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("Step 1-4: Extracting, cleaning, chunking...")
    records = build_corpus(JUDGMENTS_DIR)

    print("\nStep 5: Embedding chunks (downloads model on first run)...")
    embeddings, model = embed_chunks(records)

    print("\nStep 6: Building FAISS index...")
    index = build_faiss_index(embeddings)
    save_index(index, records, EMBEDDING_MODEL_NAME)

    print("\nStep 7: Running test queries...\n")
    test_queries = [
        "Can a person be acquitted if there is insufficient evidence?",
        "What happens if a cheque is dishonoured due to insufficient funds?",
        "Is time of the essence in a property sale agreement?",
    ]

    for q in test_queries:
        results = search(q, index, records, model, top_k=2)
        pretty_print_results(q, results)

    print("\n\nDone. To query again later without re-embedding, use load_index() + search().")