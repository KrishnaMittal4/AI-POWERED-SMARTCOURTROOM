from private_evidence_verification import verify_private_answer

def run():
    passages=[
      {'source_scope':'private','source_file':'FIR.pdf','page':4,'raw_text':'The complainant alleged that the accused received Rs 5 lakh.','case_role':'ALLEGATION'},
      {'source_scope':'private','source_file':'Bank.pdf','page':7,'raw_text':'Bank records show a transfer of Rs 5 lakh to the account.','case_role':'FINANCIAL_EVIDENCE'},
    ]
    r=verify_private_answer('The complainant alleged that the accused received Rs 5 lakh.',passages)
    assert r['verification_type']=='private_evidence'
    assert r['claims'][0]['status']=='supported'
    assert r['claims'][0]['attribution']['status']=='allegation'
    assert r['claims'][0]['sources'][0]['page']==4
    print('PASS private evidence verification')
if __name__=='__main__': run()
