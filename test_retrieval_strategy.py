import os
from pathlib import Path

def test_env_example_has_retrieval_strategy():
    text=Path('.env.example').read_text()
    assert 'RAG_RETRIEVAL_STRATEGY=improved' in text
    assert 'RAG_BM25_RESCUE_DOCS=5' in text
    assert 'RAG_RERANK_STABILITY=0.25' in text

def test_search_exposes_strategy_controls():
    text=Path('rag_pipeline.py').read_text()
    assert 'retrieval_strategy: str = None' in text
    assert 'bm25_rescue_docs: int = None' in text
    assert 'rerank_stability: float = None' in text
    assert 'final_rank_score' in text
    assert 'os.getenv("RAG_RETRIEVAL_STRATEGY", "improved")' in text
