"""
Test LangGraph Integration for Smart Courtroom
==============================================
Verifies:
1. Compilation of MootCourtState and Moot Court StateGraph workflow
2. Compilation of LegalRAGState and Evaluator-Optimizer Corrective RAG workflow
3. Graph node transitions and state updates with mock inputs
"""

from unittest.mock import patch, MagicMock
from graphs import (
    build_moot_court_graph,
    build_legal_rag_graph,
    run_moot_court_graph,
    run_legal_rag_graph,
)


def test_moot_court_graph_compilation():
    graph = build_moot_court_graph()
    assert graph is not None, "Moot Court graph failed to compile"
    # Check graph nodes exist
    nodes = set(graph.nodes.keys())
    assert "dual_retrieval" in nodes
    assert "petitioner_counsel" in nodes
    assert "respondent_counsel" in nodes
    assert "bench_judgment" in nodes
    print("PASS: Moot Court StateGraph compiled with nodes:", nodes)


def test_legal_rag_graph_compilation():
    graph = build_legal_rag_graph()
    assert graph is not None, "Legal RAG graph failed to compile"
    nodes = set(graph.nodes.keys())
    assert "query_analysis" in nodes
    assert "hybrid_retrieval" in nodes
    assert "evidence_grading" in nodes
    assert "answer_generation" in nodes
    assert "citation_verification" in nodes
    assert "reflection_and_critique" in nodes
    assert "out_of_scope_fallback" in nodes
    print("PASS: Legal RAG StateGraph compiled with nodes:", nodes)


def test_moot_court_graph_mock_execution():
    with patch("graphs.moot_court_graph.gemini_configured", return_value=True), \
         patch("graphs.moot_court_graph._retrieve_for_perspective", return_value=[{"case_name": "Test v. State", "text": "precedent"}]), \
         patch("graphs.moot_court_graph._call_groq") as mock_groq, \
         patch("graphs.moot_court_graph._call_gemini_or_fallback") as mock_judge:
        
        mock_groq.return_value = ("Submission content", "Groq (mock)")
        mock_judge.return_value = ("Order: Petition Dismissed with costs.", {"provider": "gemini", "model": "gemini-flash"})

        res = run_moot_court_graph(
            dispute="Test dispute regarding s.138 NI Act vicarious liability",
            index=None,
            records=[],
            embed_model=None,
            groq_client=MagicMock(),
        )

        assert res["petitioner"]["argument"] == "Submission content"
        assert res["respondent"]["argument"] == "Submission content"
        assert "Petition Dismissed" in res["bench"]["verdict"]
        assert res["bench"]["prevailing_party"] == "Respondent"
        assert res["graph_execution"]["orchestrator"] == "LangGraph StateGraph"
        assert "dual_retrieval" in res["graph_execution"]["nodes_executed"]
        assert "bench_judgment" in res["graph_execution"]["nodes_executed"]
        print("PASS: Moot Court graph simulated successfully through all 4 nodes!")


def test_legal_rag_graph_mock_execution():
    with patch("graphs.rag_graph.search") as mock_search, \
         patch("graphs.rag_graph.out_of_scope", return_value=(False, 0.72)), \
         patch("graphs.rag_graph.route_task") as mock_route, \
         patch("graphs.rag_graph.verify_answer") as mock_verify:
        
        mock_search.return_value = [{
            "case_name": "Satwant Singh v. Assistant Passport Officer",
            "source_file": "satwant_singh.pdf",
            "score": 0.72,
            "text": "Right to travel abroad is part of personal liberty under Article 21.",
        }]
        mock_route.return_value = {
            "ok": True,
            "text": "Under Satwant Singh v. Assistant Passport Officer, personal liberty includes travel.",
        }
        mock_verify.return_value = {
            "unverifiable_citations": [],
            "citations": [{
                "case_name": "Satwant Singh v. Assistant Passport Officer",
                "evidence_strength": "STRONG",
            }],
        }

        res = run_legal_rag_graph(
            query="Is passport impounding a violation of Article 21?",
            index=MagicMock(),
            records=[{"source_file": "satwant.pdf"}],
            embed_model=MagicMock(),
            client=MagicMock(),
            top_k=1,
            verify=True,
        )

        assert "Satwant Singh" in res["answer"]
        assert res["not_found"] is False
        assert res["graph_execution"]["orchestrator"] == "LangGraph StateGraph"
        assert "hybrid_retrieval" in res["graph_execution"]["nodes_executed"]
        assert "citation_verification" in res["graph_execution"]["nodes_executed"]
        print("PASS: Legal RAG Evaluator-Optimizer graph executed successfully!")


if __name__ == "__main__":
    test_moot_court_graph_compilation()
    test_legal_rag_graph_compilation()
    test_moot_court_graph_mock_execution()
    test_legal_rag_graph_mock_execution()
    print("\nALL LANGGRAPH INTEGRATION TESTS PASSED PERFECTLY!")
