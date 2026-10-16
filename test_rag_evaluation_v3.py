from rag_evaluation import _expected_match, _relevance_map

def test_expected_match_is_exact_after_normalization():
    target={'source_file':'2023_2023_10_913_916_EN.pdf','case_name':'Target Case'}
    other={'source_file':'2023_10_724_741_EN.pdf','case_name':'Other Case'}
    assert _expected_match(target,'2023_10_913_916_EN.pdf')
    assert not _expected_match(other,'2023_10_913_916_EN.pdf')

def test_one_label_does_not_expand_to_unrelated_cases():
    records=[
      {'source_file':'2023_2023_10_913_916_EN.pdf','case_name':'Target Case'},
      {'source_file':'2023_10_724_741_EN.pdf','case_name':'Other Case'},
    ]
    q={'query':'x','relevance':[{'judgment':'2023_10_913_916_EN.pdf','grade':3}]}
    rel=_relevance_map(records,q)
    assert len(rel)==1
