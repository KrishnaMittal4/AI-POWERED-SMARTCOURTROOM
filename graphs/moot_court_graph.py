"""
Moot Court LangGraph Multi-Agent Orchestration
==============================================
Implements a stateful, graph-based adversarial courtroom simulation using LangGraph:
- START -> Dual Retrieval -> Petitioner Counsel -> Respondent Counsel -> Presiding Bench -> END

Each legal participant operates as an isolated node modifying a shared courtroom state.
"""

import logging
from typing import Any, Dict, List, Optional, TypedDict
from groq import Groq
from langgraph.graph import StateGraph, START, END

from moot_court import (
    _format_passages,
    _retrieve_for_perspective,
    _call_groq,
    _call_gemini_or_fallback,
)
from llm_router import gemini_configured

logger = logging.getLogger(__name__)


class MootCourtState(TypedDict, total=False):
    """Courtroom transcript state tracked across all agent nodes."""
    dispute: str
    index: Any
    records: Optional[List[Dict[str, Any]]]
    embed_model: Any
    groq_client: Optional[Groq]
    
    # Retrieved corpus evidence
    petitioner_passages: List[Dict[str, Any]]
    respondent_passages: List[Dict[str, Any]]
    petitioner_docs_text: str
    respondent_docs_text: str

    # Counsel submissions
    petitioner_argument: str
    petitioner_model: str
    respondent_argument: str
    respondent_model: str

    # Judicial adjudication
    judge_verdict: str
    judge_meta: Dict[str, Any]
    disposition: str
    winner: str

    # StateGraph execution metadata
    round_count: int
    max_rounds: int
    node_history: List[str]


def dual_retrieval_node(state: MootCourtState) -> Dict[str, Any]:
    """Node 1: Dual-perspective FAISS vector retrieval for Petitioner & Respondent."""
    history = list(state.get("node_history", []))
    history.append("dual_retrieval")

    dispute = state["dispute"]
    index = state.get("index")
    records = state.get("records")
    embed_model = state.get("embed_model")

    # Targeted retrieval query expansion
    petitioner_passages = _retrieve_for_perspective(
        f"{dispute} liability violation strict interpretation maintainable statutory breach",
        index, records, embed_model, top_k=3
    )
    respondent_passages = _retrieve_for_perspective(
        f"{dispute} not liable exception defense quash distinguished lack of evidence bona fide",
        index, records, embed_model, top_k=3
    )

    return {
        "petitioner_passages": petitioner_passages,
        "respondent_passages": respondent_passages,
        "petitioner_docs_text": _format_passages(petitioner_passages),
        "respondent_docs_text": _format_passages(respondent_passages),
        "node_history": history,
    }


def petitioner_counsel_node(state: MootCourtState) -> Dict[str, Any]:
    """Node 2: Petitioner Counsel framing the primary charge and citing corpus authorities."""
    history = list(state.get("node_history", []))
    history.append("petitioner_counsel")

    groq_client = state.get("groq_client")
    dispute = state["dispute"]
    petitioner_docs = state.get("petitioner_docs_text", "")

    petitioner_system = """You are Senior Advocate for the Petitioner/Prosecution in a prestigious High Court / Supreme Court bench.
Your task:
- Argue forcefully in favor of the Petitioner based on the statutory scheme and judicial precedents.
- Structure your submission clearly with:
  1. Primary Contention (The core violation/claim)
  2. Legal Foundation & Statutory Mandate
  3. Precedents & Corpus Evidentiary Support (Cite cases provided accurately)
  4. Prayer / Relief Sought
Be formal, authoritative, and persuasive in common law courtroom tradition.
Keep length to 350-450 words."""

    petitioner_prompt = f"""DISPUTE / PROPOSITION BEFORE THE COURT:
{dispute}

RELEVANT SUPPORTING PRECEDENTS & PASSAGES IN CORPUS:
{petitioner_docs}

Present the Petitioner's opening oral submission to the Bench:"""

    argument, model_tag = _call_groq(groq_client, petitioner_prompt, petitioner_system)

    return {
        "petitioner_argument": argument,
        "petitioner_model": model_tag,
        "node_history": history,
    }


def respondent_counsel_node(state: MootCourtState) -> Dict[str, Any]:
    """Node 3: Respondent Counsel delivering direct rebuttal and raising defenses."""
    history = list(state.get("node_history", []))
    history.append("respondent_counsel")

    groq_client = state.get("groq_client")
    dispute = state["dispute"]
    petitioner_arg = state.get("petitioner_argument", "")
    respondent_docs = state.get("respondent_docs_text", "")

    respondent_system = """You are Senior Advocate for the Respondent/Defense in this High Court / Supreme Court bench.
Your task:
- Directly rebut the Petitioner's contentions.
- Distinguish the precedents cited by the Petitioner on facts and ratio.
- Argue exceptions, bona fides, lack of statutory ingredients, or contrary judicial authorities.
- Structure your submission clearly with:
  1. Preliminary Objections / Counter-Plea
  2. Rebuttal & Distinguishing of Petitioner's Authorities
  3. Defense Precedents & Statutory Safeguards (Cite cases provided)
  4. Prayer for Dismissal / Relief
Be sharp, forensic, and respectful of the Bench.
Keep length to 350-450 words."""

    respondent_prompt = f"""DISPUTE / PROPOSITION BEFORE THE COURT:
{dispute}

PETITIONER COUNSEL'S SUBMISSION:
{petitioner_arg}

RELEVANT DEFENSE PRECEDENTS & PASSAGES IN CORPUS:
{respondent_docs}

Present the Respondent's counter-submission and rebuttal to the Bench:"""

    argument, model_tag = _call_groq(groq_client, respondent_prompt, respondent_system)

    return {
        "respondent_argument": argument,
        "respondent_model": model_tag,
        "node_history": history,
    }


def bench_judgment_node(state: MootCourtState) -> Dict[str, Any]:
    """Node 4: Division Bench evaluating competing arguments and issuing judicial order."""
    history = list(state.get("node_history", []))
    history.append("bench_judgment")

    groq_client = state.get("groq_client")
    dispute = state["dispute"]
    petitioner_arg = state.get("petitioner_argument", "")
    respondent_arg = state.get("respondent_argument", "")
    petitioner_docs = state.get("petitioner_docs_text", "")
    respondent_docs = state.get("respondent_docs_text", "")

    judge_system = """You are the Presiding Chief Justice of the Division Bench.
Deliver a reasoned judicial interim order / final judgment on the submissions.
Format your response with the following structured sections:
1. BENCH ASSESSMENT: Brief judicial evaluation of Petitioner's arguments and Respondent's counter-pleas.
2. DELIBERATION ON PRECEDENTS: Critical analysis of how the cited authorities apply or are distinguished.
3. RATIO DECIDENDI: The authoritative legal test or principle enunciated by this Bench (bolded and numbered).
4. FINAL DISPOSITION: Explicitly state the outcome (e.g. "Petition Allowed", "Petition Dismissed", "Criminal Proceedings Quashed", or "Interim Stay Granted") with brief directions.

Maintain judicial gravitas, impartiality, and legal rigor. Length: 400-550 words."""

    judge_prompt = f"""CASE TITLE / DISPUTE:
{dispute}

SUBMISSIONS OF PETITIONER COUNSEL:
{petitioner_arg}

SUBMISSIONS OF RESPONDENT COUNSEL:
{respondent_arg}

CORPUS AUTHORITIES REFERENCED:
Petitioner authorities:
{petitioner_docs}

Respondent authorities:
{respondent_docs}

Deliver the official reasoned Judicial Order of the Bench:"""

    judge_verdict, judge_meta = _call_gemini_or_fallback(judge_prompt, judge_system, groq_client=groq_client)

    # Determine winning side & disposition summary
    disposition = "Disposed with Directions"
    lower_verdict = judge_verdict.lower()
    if any(k in lower_verdict for k in [
        "petition allowed", "relief granted", "petitioner's argument is well-founded",
        "proceedings quashed", "quashing the complaint"
    ]):
        disposition = "Petition Allowed (In Favor of Petitioner)"
        winner = "Petitioner"
    elif any(k in lower_verdict for k in [
        "petition dismissed", "no merit in the petition", "respondent's contention is upheld",
        "complaint is maintainable"
    ]):
        disposition = "Petition Dismissed (In Favor of Respondent)"
        winner = "Respondent"
    else:
        winner = "Balanced / Directions Issued"

    return {
        "judge_verdict": judge_verdict,
        "judge_meta": judge_meta,
        "disposition": disposition,
        "winner": winner,
        "node_history": history,
    }


def build_moot_court_graph():
    """Compiles the LangGraph StateGraph workflow for Moot Court."""
    workflow = StateGraph(MootCourtState)

    # Add agent nodes
    workflow.add_node("dual_retrieval", dual_retrieval_node)
    workflow.add_node("petitioner_counsel", petitioner_counsel_node)
    workflow.add_node("respondent_counsel", respondent_counsel_node)
    workflow.add_node("bench_judgment", bench_judgment_node)

    # Establish linear and conditional edges
    workflow.add_edge(START, "dual_retrieval")
    workflow.add_edge("dual_retrieval", "petitioner_counsel")
    workflow.add_edge("petitioner_counsel", "respondent_counsel")
    workflow.add_edge("respondent_counsel", "bench_judgment")
    workflow.add_edge("bench_judgment", END)

    return workflow.compile()


# Singleton compiled graph instance
_compiled_moot_graph = None


def get_moot_court_graph():
    global _compiled_moot_graph
    if _compiled_moot_graph is None:
        _compiled_moot_graph = build_moot_court_graph()
    return _compiled_moot_graph


def run_moot_court_graph(
    dispute: str,
    index=None,
    records: list = None,
    embed_model=None,
    groq_client: Optional[Groq] = None,
) -> dict:
    """
    Executes the Moot Court simulation via compiled LangGraph StateGraph.
    Returns response compatible with existing frontend /moot-court contract.
    """
    if not groq_client and not gemini_configured():
        raise ValueError("Configure GEMINI_API_KEY or GROQ_API_KEY for Moot Court.")

    graph = get_moot_court_graph()

    initial_state: MootCourtState = {
        "dispute": dispute,
        "index": index,
        "records": records,
        "embed_model": embed_model,
        "groq_client": groq_client,
        "round_count": 1,
        "max_rounds": 1,
        "node_history": [],
    }

    final_state = graph.invoke(initial_state)

    judge_meta = final_state.get("judge_meta", {})

    return {
        "dispute": final_state["dispute"],
        "petitioner": {
            "counsel": "Senior Counsel for Petitioner",
            "model": final_state.get("petitioner_model", "Groq"),
            "argument": final_state.get("petitioner_argument", ""),
            "citations": final_state.get("petitioner_passages", []),
        },
        "respondent": {
            "counsel": "Senior Counsel for Respondent",
            "model": final_state.get("respondent_model", "Groq"),
            "argument": final_state.get("respondent_argument", ""),
            "citations": final_state.get("respondent_passages", []),
        },
        "bench": {
            "bench_title": "Division Bench / High Court",
            "model": f"{judge_meta.get('provider', 'AI').title()} ({judge_meta.get('model', 'gemini')})",
            "provider": judge_meta.get("provider", "gemini"),
            "fallback_reason": judge_meta.get("fallback_reason"),
            "verdict": final_state.get("judge_verdict", ""),
            "disposition": final_state.get("disposition", ""),
            "prevailing_party": final_state.get("winner", "Balanced"),
        },
        "graph_execution": {
            "orchestrator": "LangGraph StateGraph",
            "nodes_executed": final_state.get("node_history", []),
            "version": "1.2.x",
        },
    }
