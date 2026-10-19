"""
Corrective Legal RAG (CRAG) & Citation Self-Correction LangGraph Workflow
=======================================================================
Implements an Evaluator-Optimizer stateful graph for Legal QA:
1. Query Analysis & Legal HyDE Expansion
2. Hybrid Retrieval (FAISS + BM25 + RRF + Cross-Encoder)
3. Evidence Grading Guardrail (Threshold & Relevance Check)
4. Legal Generation Node (incorporating past critique on retry)
5. Citation & Hallucination Verifier Node
6. Evaluator-Optimizer Loop: If hallucinated citations or ratio errors are detected,
   the graph reflects on the error, formulates an architectural critique, and
   regenerates the answer within a bounded retry loop (max_retries=2).
"""

import logging
from typing import Any, Dict, List, Optional, TypedDict
from groq import Groq
from langgraph.graph import StateGraph, START, END

from rag_pipeline import search
from generate_answer import (
    MIN_RETRIEVAL_SCORE,
    WEAK_RETRIEVAL_SCORE,
    ALLOW_STATUTORY_FALLBACK,
    NOT_COVERED_MESSAGE,
    STATUTORY_DISCLAIMER,
    generate_legal_hyde,
    out_of_scope,
    _source_out,
    out_of_scope_answer,
    build_prompt,
    GROQ_MODEL,
)
from citation_verification import verify_answer
from llm_router import route_task

logger = logging.getLogger(__name__)


class LegalRAGState(TypedDict, total=False):
    """Execution state for Corrective Legal RAG."""
    query: str
    index: Any
    records: Optional[List[Dict[str, Any]]]
    embed_model: Any
    client: Optional[Groq]
    top_k: int
    verify: bool
    rerank: bool
    reranker_model: Any

    # Query expansion & HyDE
    search_query: str
    rewritten_query: Optional[str]
    hyde_info: Optional[Dict[str, Any]]

    # Retrieval results
    passages: List[Dict[str, Any]]
    sources: List[Dict[str, Any]]
    top_score: float
    threshold: float
    weak_match: bool
    not_found: bool

    # Generation & Self-Correction
    answer: str
    verification: Optional[Dict[str, Any]]
    retry_count: int
    max_retries: int
    critique: Optional[str]
    correction_history: List[str]
    node_history: List[str]


def query_analysis_node(state: LegalRAGState) -> Dict[str, Any]:
    """Node 1: Analyzes query and runs Legal HyDE query expansion."""
    history = list(state.get("node_history", []))
    history.append("query_analysis")

    query = state["query"]
    client = state.get("client")

    search_query = query
    rewritten_query = None
    hyde_info = None

    try:
        hyde = generate_legal_hyde(query, client)
        if hyde and hyde.get("search_query"):
            search_query = hyde["search_query"]
            rewritten_query = search_query if search_query != query else None
            hyde_info = hyde
    except Exception as e:
        logger.warning(f"HyDE expansion skipped: {e}")

    return {
        "search_query": search_query,
        "rewritten_query": rewritten_query,
        "hyde_info": hyde_info,
        "node_history": history,
    }


def retrieval_node(state: LegalRAGState) -> Dict[str, Any]:
    """Node 2: Executes Hybrid Retrieval (Dense FAISS + Sparse BM25 + RRF + Cross-Encoder)."""
    history = list(state.get("node_history", []))
    history.append("hybrid_retrieval")

    search_query = state.get("search_query") or state["query"]
    index = state.get("index")
    records = state.get("records") or []
    embed_model = state.get("embed_model")
    top_k = state.get("top_k", 3)
    rerank = state.get("rerank", True)
    reranker_model = state.get("reranker_model")

    passages = search(
        query=search_query,
        index=index,
        records=records,
        embed_model=embed_model,
        top_k=top_k,
        rerank=rerank,
        reranker_model=reranker_model,
    )

    sources = [_source_out(p) for p in passages]

    return {
        "passages": passages,
        "sources": sources,
        "node_history": history,
    }


def evidence_grading_node(state: LegalRAGState) -> Dict[str, Any]:
    """Node 3: Evaluates retrieval quality and applies score guardrails."""
    history = list(state.get("node_history", []))
    history.append("evidence_grading")

    passages = state.get("passages", [])
    if not passages:
        return {
            "not_found": True,
            "top_score": 0.0,
            "threshold": MIN_RETRIEVAL_SCORE,
            "weak_match": True,
            "node_history": history,
        }

    refuse, top_score = out_of_scope(passages)
    return {
        "not_found": refuse,
        "top_score": top_score,
        "threshold": MIN_RETRIEVAL_SCORE,
        "weak_match": top_score < WEAK_RETRIEVAL_SCORE,
        "node_history": history,
    }


def out_of_scope_node(state: LegalRAGState) -> Dict[str, Any]:
    """Fallback node if retrieved evidence fails minimum threshold."""
    history = list(state.get("node_history", []))
    history.append("out_of_scope_fallback")

    client = state.get("client")
    query = state["query"]

    answer, _is_fallback = out_of_scope_answer(query, client)

    return {
        "answer": answer,
        "verification": None,
        "node_history": history,
    }


def generation_node(state: LegalRAGState) -> Dict[str, Any]:
    """Node 4: Generates judicial answer, conditioned on critique if in retry loop."""
    history = list(state.get("node_history", []))
    history.append("answer_generation")

    query = state["query"]
    passages = state.get("passages", [])
    client = state.get("client")
    critique = state.get("critique")

    base_prompt = build_prompt(query, passages)

    if critique:
        prompt = (
            f"{base_prompt}\n\n"
            f"CRITICAL CITATION FEEDBACK FROM AUDIT:\n"
            f"{critique}\n\n"
            f"MANDATE: Regenerate the legal answer strictly correcting the above flaws. "
            f"Do NOT reference or hallucinate any unverified authorities. Use only the corpus passages provided."
        )
    else:
        prompt = base_prompt

    # Generation via llm_router with Groq/Gemini resilience
    result = route_task(
        "query", prompt, groq_client=client, purpose="reason",
        max_tokens=1800, temperature=0.15,
    )
    answer = result.get("text", "") if result.get("ok") else "Error generating legal answer."

    return {
        "answer": answer,
        "critique": None,  # Consumed
        "node_history": history,
    }


def citation_verification_node(state: LegalRAGState) -> Dict[str, Any]:
    """Node 5: Evaluates generated answer against corpus records for citations."""
    history = list(state.get("node_history", []))
    history.append("citation_verification")

    if not state.get("verify", True):
        return {"verification": None, "node_history": history}

    answer = state.get("answer", "")
    passages = state.get("passages", [])
    records = state.get("records") or []
    client = state.get("client")

    verification = None
    try:
        verification = verify_answer(answer, passages, records, client)
        if verification and "citations" in verification:
            from legal_intelligence import enrich_citations_with_precedent_status
            verification["citations"] = enrich_citations_with_precedent_status(verification["citations"], client)
    except Exception as e:
        logger.warning(f"Citation verification error: {e}")

    return {
        "verification": verification,
        "node_history": history,
    }


def reflection_node(state: LegalRAGState) -> Dict[str, Any]:
    """Evaluator-Optimizer reflection: analyzes hallucinated or ungrounded citations to guide regeneration."""
    history = list(state.get("node_history", []))
    history.append("reflection_and_critique")

    verification = state.get("verification") or {}
    unverifiable = verification.get("unverifiable_citations", [])
    citations = verification.get("citations", [])

    weak_citations = [
        c.get("case_name") for c in citations
        if c.get("evidence_strength") == "NONE" and c.get("case_name")
    ]

    critique_items = []
    if unverifiable:
        critique_items.append(f"The previous draft hallucinated case names not found in corpus: {', '.join(unverifiable)}.")
    if weak_citations:
        critique_items.append(f"The following citations lacked supporting text in retrieved passages: {', '.join(weak_citations)}.")

    critique_str = " ".join(critique_items) if critique_items else "Please refine legal precision and citations."

    retry_count = state.get("retry_count", 0) + 1
    corr_history = list(state.get("correction_history", []))
    corr_history.append(f"Retry {retry_count}: {critique_str}")

    return {
        "critique": critique_str,
        "retry_count": retry_count,
        "correction_history": corr_history,
        "node_history": history,
    }


# Routing conditions
def route_evidence(state: LegalRAGState) -> str:
    """Routes based on evidence sufficiency."""
    if state.get("not_found", False):
        return "out_of_scope"
    return "generate"


def route_citation_check(state: LegalRAGState) -> str:
    """Evaluator-Optimizer routing: triggers self-correction if hallucinations exist and retries remain."""
    if not state.get("verify", True):
        return END

    verification = state.get("verification") or {}
    unverifiable = verification.get("unverifiable_citations", [])
    
    # Check for severe citation hallucination
    has_hallucinations = len(unverifiable) > 0
    current_retries = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 1)

    if has_hallucinations and current_retries < max_retries:
        logger.info(f"LangGraph CRAG triggering self-correction loop (attempt {current_retries + 1}/{max_retries})")
        return "reflect_and_retry"

    return END


def build_legal_rag_graph():
    """Compiles the Evaluator-Optimizer Corrective RAG LangGraph workflow."""
    workflow = StateGraph(LegalRAGState)

    # Register graph nodes
    workflow.add_node("query_analysis", query_analysis_node)
    workflow.add_node("hybrid_retrieval", retrieval_node)
    workflow.add_node("evidence_grading", evidence_grading_node)
    workflow.add_node("out_of_scope_fallback", out_of_scope_node)
    workflow.add_node("answer_generation", generation_node)
    workflow.add_node("citation_verification", citation_verification_node)
    workflow.add_node("reflection_and_critique", reflection_node)

    # Edges
    workflow.add_edge(START, "query_analysis")
    workflow.add_edge("query_analysis", "hybrid_retrieval")
    workflow.add_edge("hybrid_retrieval", "evidence_grading")

    # Conditional routing after grading
    workflow.add_conditional_edges(
        "evidence_grading",
        route_evidence,
        {
            "out_of_scope": "out_of_scope_fallback",
            "generate": "answer_generation",
        },
    )
    workflow.add_edge("out_of_scope_fallback", END)
    workflow.add_edge("answer_generation", "citation_verification")

    # Conditional routing after verification (Evaluator-Optimizer Loop)
    workflow.add_conditional_edges(
        "citation_verification",
        route_citation_check,
        {
            "reflect_and_retry": "reflection_and_critique",
            END: END,
        },
    )
    # Loop back from reflection to generator
    workflow.add_edge("reflection_and_critique", "answer_generation")

    return workflow.compile()


_compiled_rag_graph = None


def get_legal_rag_graph():
    global _compiled_rag_graph
    if _compiled_rag_graph is None:
        _compiled_rag_graph = build_legal_rag_graph()
    return _compiled_rag_graph


def run_legal_rag_graph(
    query: str,
    index=None,
    records: list = None,
    embed_model=None,
    client: Optional[Groq] = None,
    top_k: int = 3,
    verify: bool = True,
    rerank: bool = True,
    reranker_model=None,
    max_retries: int = 1,
) -> dict:
    """
    Executes the Corrective RAG graph with Evaluator-Optimizer citation feedback.
    Returns payload compatible with existing /query endpoint response model.
    """
    graph = get_legal_rag_graph()

    initial_state: LegalRAGState = {
        "query": query,
        "index": index,
        "records": records,
        "embed_model": embed_model,
        "client": client,
        "top_k": top_k,
        "verify": verify,
        "rerank": rerank,
        "reranker_model": reranker_model,
        "retry_count": 0,
        "max_retries": max_retries,
        "correction_history": [],
        "node_history": [],
    }

    final_state = graph.invoke(initial_state)

    return {
        "answer": final_state.get("answer", ""),
        "sources": final_state.get("sources", []),
        "verification": final_state.get("verification"),
        "not_found": final_state.get("not_found", False),
        "top_score": final_state.get("top_score"),
        "threshold": final_state.get("threshold", MIN_RETRIEVAL_SCORE),
        "weak_match": final_state.get("weak_match", False),
        "rewritten_query": final_state.get("rewritten_query"),
        "hyde_info": final_state.get("hyde_info"),
        "graph_execution": {
            "orchestrator": "LangGraph StateGraph",
            "pattern": "Corrective RAG (CRAG) + Evaluator-Optimizer Citation Self-Correction",
            "nodes_executed": final_state.get("node_history", []),
            "retries_performed": final_state.get("retry_count", 0),
            "correction_audit": final_state.get("correction_history", []),
        },
    }
