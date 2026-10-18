"""
RAG Generation Step — Groq API
================================
Completes the loop: Query -> FAISS retrieval -> Groq LLM -> grounded answer + citations
 
Setup:
    1. pip install -r requirements.txt
    2. cp .env.example .env
    3. Put your real Groq key in .env (GROQ_API_KEY=gsk_xxxxx)
    4. Make sure you've already run rag_pipeline.py once (it builds and
       saves the FAISS index to index_store/)
 
Usage:
    python generate_answer.py
"""
 
import os
from dotenv import load_dotenv
 
load_dotenv()  # reads .env and populates os.environ -- MUST run before any
# other local module is imported below. citation_verification.py no longer
# depends on this ordering (it reads GEMINI_API_KEY lazily at call time),
# but keeping load_dotenv() first here is still the correct, defensive
# pattern: it avoids the same import-order trap biting any future
# module-level os.getenv(...) added to this file or anything it imports.
 
from groq import Groq
 
from rag_pipeline import load_index, load_embedding_model, search, INDEX_DIR, load_reranker_model
from citation_verification import verify_answer, pretty_print_verification
 
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# llama-3.3-70b-versatile was deprecated by Groq on 08/16/26.
# openai/gpt-oss-120b is Groq's recommended replacement (strong reasoning + tool calling).
GROQ_MODEL = "openai/gpt-oss-120b"
 
# Retrieval-score guardrails (cosine similarity of the best retrieved chunk).
# Calibrated on minilm_30docs_final.json: answerable queries scored 0.54-0.75,
# the GST query 0.39 and the trademark query 0.52. Only two unanswerable
# queries exist, so treat these as starting values and re-tune after you add
# more documents and test queries.
#   below MIN_RETRIEVAL_SCORE  -> do not call the LLM, say "not covered"
#   below WEAK_RETRIEVAL_SCORE -> answer, but flag the match as weak
MIN_RETRIEVAL_SCORE = float(os.getenv("MIN_RETRIEVAL_SCORE", "0.54"))
WEAK_RETRIEVAL_SCORE = float(os.getenv("WEAK_RETRIEVAL_SCORE", "0.55"))

# Dense cosine alone cannot fully separate answerable from unanswerable queries
# on this corpus (eval calibration: separable=false -- lowest answerable top
# score 0.552, highest unanswerable 0.597). Optional second gate: when the best
# dense score is in the ambiguous band (MIN <= score < RERANK_GATE_BELOW), also
# require the cross-encoder's top score to reach RERANK_MIN_SCORE. Unset =
# disabled. The cross-encoder emits raw logits, so calibrate RERANK_MIN_SCORE on
# your own eval set (compare rerank scores of answerable vs unanswerable
# queries in that band) before enabling it.
RERANK_GATE_BELOW = float(os.getenv("RERANK_GATE_BELOW", "0.62"))
_rr = os.getenv("RERANK_MIN_SCORE", "").strip()
RERANK_MIN_SCORE = float(_rr) if _rr else None

# When the corpus does not cover a question, the default is to SAY SO. Setting
# ALLOW_STATUTORY_FALLBACK=1 additionally lets the model write a general-law
# overview from its own knowledge. That text is NOT grounded in the corpus and
# its citations are NOT verified, so it is always prefixed with a disclaimer.
ALLOW_STATUTORY_FALLBACK = os.getenv("ALLOW_STATUTORY_FALLBACK", "1") == "1"

NOT_COVERED_MESSAGE = (
    "The judgments in this corpus do not cover this question well enough to answer "
    "reliably, so no answer was written. The closest passages are listed under Sources."
)
STATUTORY_DISCLAIMER = (
    "> ⚠️ **Not from your uploaded judgment(s).** The uploaded document did not cover this question. "
    "The answer below is synthesized from general legal statutory knowledge — **not grounded in "
    "the uploaded document and citations are not verified against the PDF**. Please verify against "
    "the Bare Act or official law reports.\n\n"
)


def out_of_scope(passages: list) -> tuple[bool, float]:
    """Decide whether retrieval is too weak to answer from. Returns (refuse, top_score)."""
    top_score = max(p["score"] for p in passages)
    if top_score < MIN_RETRIEVAL_SCORE:
        return True, top_score
    if RERANK_MIN_SCORE is not None and top_score < RERANK_GATE_BELOW:
        rr = [p["rerank_score"] for p in passages if "rerank_score" in p]
        if rr and max(rr) < RERANK_MIN_SCORE:
            return True, top_score
    return False, top_score


def out_of_scope_answer(query: str, client: Groq) -> tuple[str, bool]:
    """(answer_text, is_statutory_fallback) for a question the corpus does not cover."""
    if not ALLOW_STATUTORY_FALLBACK:
        return NOT_COVERED_MESSAGE, False
    return STATUTORY_DISCLAIMER + generate_general_statute_fallback(query, client), True



def friendly_llm_error(e: Exception) -> str:
    """User-facing message for an LLM failure. The raw error (which can contain
    provider/account details) goes to the server log only."""
    print(f"  LLM error: {type(e).__name__}: {e}")
    try:
        import groq
        if isinstance(e, groq.RateLimitError):
            return "The AI service is busy right now (rate limit reached). Please wait a minute and try again."
    except Exception:
        pass
    return "The AI service had a problem. Please try again."


# ---------------------------------------------------------------------------
# LEGAL HyDE (Hypothetical Document Embeddings) & QUERY EXPANSION
# ---------------------------------------------------------------------------
def generate_legal_hyde(query: str, client: Groq) -> dict:
    """Generate high-precision Legal HyDE (Hypothetical Document Embeddings)
    and identify statutory acts/sections using fast Groq inference.

    Returns dict:
      {
        "search_query": str,        # Combined query + hypothetical judicial excerpt
        "statutes": list[str],      # Identified Acts & Sections e.g. ["NI Act s.138", "CrPC s.482"]
        "hypothetical_text": str,   # Brief formal judicial excerpt
      }
    """
    prompt = f"""You are an Indian Supreme Court research clerk and legal query expander.
Given the legal question below, generate a brief hypothetical judgment excerpt (HyDE) that a High Court or Supreme Court bench would write on this issue.

Query: "{query}"

Rules:
1. Identify relevant Indian Statutes and Section numbers (e.g. Section 138, 141 Negotiable Instruments Act; Section 482 CrPC / Section 528 BNSS; Order 39 CPC; Section 438/439 CrPC).
2. Write a 2-3 sentence hypothetical formal judicial ruling excerpt embodying the ratio decidendi with judicial vocabulary judges write in law reports.
3. Keep response brief and strictly formatted.

Format strictly as:
STATUTES: <Comma-separated Acts and Sections identified>
EXCERPT: <2-3 sentence formal judicial ruling excerpt>"""

    try:
        response = client.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=220,
        )
        content = (response.choices[0].message.content or "").strip()

        statutes = []
        excerpt = ""

        import re
        stat_match = re.search(r"STATUTES:\s*(.*?)(?:\n|EXCERPT:|$)", content, re.IGNORECASE)
        if stat_match:
            raw_stats = stat_match.group(1).strip()
            statutes = [s.strip() for s in raw_stats.split(",") if s.strip() and len(s.strip()) > 1]

        exc_match = re.search(r"EXCERPT:\s*(.*)", content, re.IGNORECASE | re.DOTALL)
        if exc_match:
            excerpt = exc_match.group(1).strip()
        elif not stat_match:
            excerpt = content

        statute_text = " ".join(statutes) if statutes else ""
        combined_search = f"{query} {statute_text} {excerpt}".strip()

        if len(combined_search) < len(query):
            combined_search = query

        return {
            "search_query": combined_search,
            "statutes": statutes[:6],
            "hypothetical_text": excerpt[:350],
        }
    except Exception as e:
        print(f"  HyDE expansion fallback ({e})")
        return {
            "search_query": query,
            "statutes": [],
            "hypothetical_text": "",
        }


def rewrite_query(query: str, client: Groq) -> str:
    """Backward-compatible wrapper around Legal HyDE for legacy callers."""
    hyde = generate_legal_hyde(query, client)
    return hyde.get("search_query") or query

 
 
def build_prompt(query: str, passages: list) -> str:
    context_blocks = []
    for p in passages:
        context_blocks.append(
            f"[Source: {p['case_name']} ({p['source_file']})]\n{p['text']}"
        )
    context = "\n\n".join(context_blocks)
 
    return f"""You are a legal research assistant. Answer the question ONLY \
using the passages provided below. Do not use any outside knowledge, \
even if you recognise a relevant precedent from general legal knowledge.
 
Every case name you write MUST be copied exactly from one of the \
[Source: ...] tags in the Context below -- do not name, describe, or attribute a \
holding to ANY case that is not one of those exact source tags, even a \
well-known or landmark one. If a relevant precedent occurs to you from \
outside knowledge, do not mention its name at all -- simply note that \
the provided passages do not cover that angle.
 
Cite the case name for every claim you make, using only the exact names \
from the [Source: ...] tags. If the passages do not contain enough \
information to answer, say so explicitly instead of guessing or filling \
the gap with outside knowledge.
 
FORMATTING & PRESENTATION:
- Structure your answer with clear Markdown headings (e.g. ## Executive Summary, ## Applicable Legal Framework, ## Judicial Precedents & Analysis, ## Key Takeaways).
- Use bullet points and bold emphasis for legal tests, statutory elements, and conditions.
- Whenever explaining multiple requirements, comparing case holdings, or listing statutory provisions, present them in a clean Markdown table (| Parameter / Issue | Legal Principle / Ratio | Source / Precedent |) for fast, structured readability.

Context:
{context}

Question: {query}

Answer (with citations):"""


def generate_answer(query: str, passages: list, client: Groq) -> str:
    prompt = build_prompt(query, passages)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,  # low temperature = grounded, less creative/hallucinated
    )
    return response.choices[0].message.content or ""


def generate_general_statute_fallback(query: str, client: Groq) -> str:
    """Generate an authoritative advisory answer from established Indian law (statutory
    law, landmark Supreme Court constitutional doctrines, or Bare Acts) when the query
    is not covered by the local judgment corpus.
    """
    fallback_prompt = f"""You are a senior Indian legal scholar and research assistant.
The user asked a legal question: "{query}"

This specific case or topic was NOT found in the user's local judgment folder.
Provide a clear, authoritative, highly structured, and user-friendly legal explanation based on established Indian Law:

1. IDENTIFY THE TRUE LEGAL SUBJECT:
   - If the query refers to a landmark Supreme Court case or constitutional doctrine (e.g., Kesavananda Bharati, Maneka Gandhi, Puttaswamy, Basic Structure, Doctrine of Severability, etc.), immediately identify it with its correct citation, bench, and core constitutional holding.
   - If the query is about a statute, section, or commercial/criminal principle (e.g., NI Act, IPC/BNS, CrPC/BNSS, CPC, arbitration), identify the relevant Acts and key section numbers.

2. PRESENTATION FORMAT (USER-FRIENDLY WITH TABLES):
   - **Executive Summary**: A crisp 2-3 sentence overview of the core subject or holding.
   - **Key Legal Framework Table**: Format the primary statutory provisions or constitutional articles in a clean Markdown table:
     | Area of Law / Subject | Principal Statute(s) / Article | Key Section(s) | Core Rule / Purpose |
   - **Precedent / Doctrine Matrix Table**: For landmark cases or key doctrines, provide a summary table:
     | Landmark Case / Doctrine | Citation & Bench | Core Holding / Ratio Decidendi | Constitutional Status |
   - **Detailed Analysis & Core Principles**: Clear numbered headings (## 1., ## 2.) explaining the legal mechanics, tests, or statutory elements.
   - **Procedural Steps & Practical Remedies Table**: When applicable, provide a practical action table:
     | Situation / Stage | Statutory Reference | Action Required | Available Remedy |

3. FORMATTING GUIDELINES:
   - Use standard Markdown tables (`| Col 1 | Col 2 |`) with clear headers.
   - Use bold headings (`##`), bullet points, and clean typography.
   - Do NOT output raw HTML tags (e.g., no `<br>` tags).
   - Maintain high academic and legal rigor.
   - If you are not certain of a case citation, bench, or section number, say so plainly instead of guessing.

Answer:"""
    try:
        response = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": fallback_prompt}],
            temperature=0.2,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        return (
            "The judgments in this corpus do not appear to cover this question, "
            f"and generating a general legal overview failed: {friendly_llm_error(e)}"
        )


 
 
def _source_out(p: dict) -> dict:
    """API-facing view of a retrieved passage. Includes the chunk text so the
    UI can show the exact passage an answer was grounded in.
 
    Uses raw_text (the chunk BEFORE the "[Case: X | Court: Y | ...]" metadata
    header rag_pipeline.py prepends for BM25/embedding matching), not the
    header-enriched text -- that header is useful internal context for the
    retrieval/generation models, but showing it to the user in the "Show
    passage" UI is just clutter (and build_prompt() below already adds its
    own separate "[Source: ...]" header to p['text'] when building the LLM
    prompt, so the raw passage was being duplicated with two headers back
    to back in both places). Falls back to p['text'] for any older index
    built before raw_text existed.
    """
    return {
        "case_name": p["case_name"],
        "source_file": p["source_file"],
        "score": p["score"],
        "case_no": p.get("case_no"),
        "text": p.get("raw_text", p.get("text", "")),
    }
 
 
def answer_query(
    query: str,
    index,
    records,
    embed_model,
    client: Groq,
    top_k: int = 3,
    verify: bool = True,
    rerank: bool = True,
    reranker_model=None,
    enable_rewrite: bool = True,
):
    """Full RAG step: (optionally) rewrite query -> retrieve -> generate -> (optionally) verify -> return.
 
    rerank=True (default) runs a Cross-Encoder over the top candidate pool
    before passing passages to the LLM.  The reranker is lazy-loaded and
    cached after the first call -- startup latency is only paid once.
    Pass reranker_model=<loaded CrossEncoder> to share a pre-loaded instance
    (e.g. from the FastAPI lifespan) and avoid loading it on each request.

    enable_rewrite=True (default) rewrites the user's query using the LLM
    before retrieval for better recall.
    """
    # Step 0: Legal HyDE & Query Expansion
    search_query = query
    rewritten_query = None
    hyde_info = None
    if enable_rewrite:
        hyde = generate_legal_hyde(query, client)
        if hyde and hyde.get("search_query"):
            search_query = hyde["search_query"]
            rewritten_query = search_query if search_query != query else None
            hyde_info = hyde

    passages = search(
        search_query, index, records, embed_model,
        top_k=top_k,
        rerank=rerank,
        reranker_model=reranker_model,
    )
    if not passages:
        return {
            "answer": "No relevant passages found in the corpus for this query.",
            "sources": [],
            "verification": None,
            "not_found": True,
            "top_score": None,
            "weak_match": False,
            "rewritten_query": rewritten_query,
            "hyde_info": hyde_info,
        }
 
    refuse, top_score = out_of_scope(passages)
 
    # Refuse instead of letting the LLM improvise from irrelevant passages.
    # Sources are still returned so the user can see what the closest
    # (but too weak) matches were.
    if refuse:
        text, is_fallback = out_of_scope_answer(query, client)
        return {
            "answer": text,
            "sources": [_source_out(p) for p in passages],
            "verification": None,
            "not_found": True,
            "statutory_fallback": is_fallback,
            "top_score": top_score,
            "threshold": MIN_RETRIEVAL_SCORE,
            "weak_match": False,
            "rewritten_query": rewritten_query,
            "hyde_info": hyde_info,
        }
 
    answer = generate_answer(query, passages, client)
    sources = [_source_out(p) for p in passages]
 
    verification = None
    if verify:
        verification = verify_answer(answer, passages, records, client)
        if verification and "citations" in verification:
            from legal_intelligence import enrich_citations_with_precedent_status
            verification["citations"] = enrich_citations_with_precedent_status(verification["citations"], client)
 
    return {
        "answer": answer,
        "sources": sources,
        "verification": verification,
        "not_found": False,
        "top_score": top_score,
        "threshold": MIN_RETRIEVAL_SCORE,
        "weak_match": top_score < WEAK_RETRIEVAL_SCORE,
        "rewritten_query": rewritten_query,
        "hyde_info": hyde_info,
    }


def generate_answer_stream(query: str, passages: list, client: Groq):
    """Yield answer tokens as they arrive from the Groq API (for SSE)."""
    prompt = build_prompt(query, passages)
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        stream=True,
    )
    for chunk in response:
        delta = chunk.choices[0].delta
        if delta and delta.content:
            yield delta.content


def answer_query_stream(
    query: str,
    index,
    records,
    embed_model,
    client: Groq,
    top_k: int = 3,
    verify: bool = True,
    rerank: bool = True,
    reranker_model=None,
    enable_rewrite: bool = True,
):
    """Generator-based RAG step for SSE streaming.

    Yields JSON-encoded SSE events:
      event: hyde         data: {hyde: {...}}
      event: sources      data: {sources, top_score, weak_match, rewritten_query, hyde_info}
      event: token        data: {token: "..."}
      event: verification data: {verification: {...}}
      event: done         data: {answer: "full accumulated answer"}
      event: error        data: {error: "..."}
    """
    import json as _json

    # Step 0: Legal HyDE & Query Expansion
    search_query = query
    rewritten_query = None
    hyde_info = None
    if enable_rewrite:
        hyde = generate_legal_hyde(query, client)
        if hyde and hyde.get("search_query"):
            search_query = hyde["search_query"]
            rewritten_query = search_query if search_query != query else None
            hyde_info = hyde

    # Emit HyDE event immediately if statutes or excerpt identified
    if hyde_info and (hyde_info.get("statutes") or hyde_info.get("hypothetical_text")):
        yield f"event: hyde\ndata: {_json.dumps({'hyde': hyde_info})}\n\n"

    # Step 1: Retrieve
    passages = search(
        search_query, index, records, embed_model,
        top_k=top_k,
        rerank=rerank,
        reranker_model=reranker_model,
    )

    if not passages:
        yield f"event: error\ndata: {_json.dumps({'error': 'No relevant passages found.', 'not_found': True, 'rewritten_query': rewritten_query, 'hyde_info': hyde_info})}\n\n"
        return

    refuse, top_score = out_of_scope(passages)
    sources = [_source_out(p) for p in passages]

    # Emit sources immediately so the UI can render them while the LLM streams
    yield f"event: sources\ndata: {_json.dumps({'sources': sources, 'top_score': top_score, 'weak_match': top_score < WEAK_RETRIEVAL_SCORE, 'not_found': refuse, 'threshold': MIN_RETRIEVAL_SCORE, 'rewritten_query': rewritten_query, 'hyde_info': hyde_info})}\n\n"

    # Too weak to answer from: say so (or, if enabled, a clearly-labelled general overview)
    if refuse:
        text, is_fallback = out_of_scope_answer(query, client)
        yield f"event: done\ndata: {_json.dumps({'answer': text, 'not_found': True, 'statutory_fallback': is_fallback})}\n\n"
        return

    # Step 2: Stream the answer token by token
    full_answer = []
    try:
        for token in generate_answer_stream(query, passages, client):
            full_answer.append(token)
            yield f"event: token\ndata: {_json.dumps({'token': token})}\n\n"
    except Exception as e:
        yield f"event: error\ndata: {_json.dumps({'error': friendly_llm_error(e)})}\n\n"
        return

    answer_text = "".join(full_answer)

    # Step 3: Verification (after generation completes)
    verification = None
    if verify:
        try:
            verification = verify_answer(answer_text, passages, records, client)
            if verification and "citations" in verification:
                from legal_intelligence import enrich_citations_with_precedent_status
                verification["citations"] = enrich_citations_with_precedent_status(verification["citations"], client)
            yield f"event: verification\ndata: {_json.dumps({'verification': verification})}\n\n"
        except Exception as e:
            yield f"event: verification\ndata: {_json.dumps({'verification': None, 'error': friendly_llm_error(e)})}\n\n"

    # Final done event with the complete answer
    yield f"event: done\ndata: {_json.dumps({'answer': answer_text})}\n\n"
 
 
if __name__ == "__main__":
    if not GROQ_API_KEY:
        raise RuntimeError(
            "GROQ_API_KEY not found. Copy .env.example to .env and add your key."
        )
 
    print("Loading saved FAISS index...")
    index, records, model_name = load_index(INDEX_DIR)
    embed_model = load_embedding_model(model_name)
 
    print("Loading Cross-Encoder re-ranker...")
    reranker = load_reranker_model()
    if reranker:
        print("  Re-ranker loaded -- retrieval: Hybrid BM25+FAISS + Cross-Encoder re-rank")
    else:
        print("  Re-ranker unavailable -- retrieval: Hybrid BM25+FAISS only")
 
    client = Groq(api_key=GROQ_API_KEY)
 
    test_queries = [
        "Can a person be acquitted if there is insufficient evidence?",
        "What happens if a cheque is dishonoured due to insufficient funds?",
    ]
 
    for q in test_queries:
        result = answer_query(
            q, index, records, embed_model, client,
            rerank=reranker is not None,
            reranker_model=reranker,
        )
        print(f"\n{'='*70}\nQUERY: {q}\n{'='*70}")
        print(f"\nANSWER:\n{result['answer']}")
        print(f"\nSOURCES USED:")
        for s in result["sources"]:
            print(f"  - {s['case_name']} ({s['source_file']}, score={s['score']:.3f})")
        if result["verification"]:
            pretty_print_verification(result["verification"])