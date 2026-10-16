"""Small regression checks for RAG Quality V2 identifier normalization.
Run with: python -m pytest test_rag_evaluation_identifiers.py
"""
from rag_evaluation import _norm, _expected_match

def test_repeated_year_filename_normalizes():
    assert _norm('2023_2023_10_824_841_EN.pdf') == _norm('2023_10_824_841_EN')

def test_case_prefix_matches_full_indian_kanoon_filename():
    rec={'source_file':'A_Sakthivel_vs_K_R_Navaneetha_Krishnan_on_29_April_2011.PDF','case_name':'A Sakthivel vs K R Navaneetha Krishnan'}
    assert _expected_match(rec,'A_Sakthivel')
