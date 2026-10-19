"""
LangGraph Orchestration Package for Smart Courtroom
==================================================
Houses StateGraph-based workflows for:
1. Moot Court Multi-Agent Adversarial Debate (`moot_court_graph`)
2. Evaluator-Optimizer Corrective Legal RAG with Citation Self-Correction (`rag_graph`)
"""

from .moot_court_graph import run_moot_court_graph, build_moot_court_graph, MootCourtState
from .rag_graph import run_legal_rag_graph, build_legal_rag_graph, LegalRAGState

__all__ = [
    "run_moot_court_graph",
    "build_moot_court_graph",
    "MootCourtState",
    "run_legal_rag_graph",
    "build_legal_rag_graph",
    "LegalRAGState",
]
