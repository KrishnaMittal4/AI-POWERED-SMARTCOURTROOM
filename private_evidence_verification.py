"""Private-case evidence verification policy.
Reuses shared claim/support primitives but applies evidence-specific attribution,
provenance, corroboration and contradiction semantics rather than precedent rules.
"""
from shared_verification import split_claims, support_score, support_status

_ALLEGATION={"ALLEGATION","POLICE_RECORD","PARTY_SUBMISSION"}
_DIRECT={"DOCUMENTARY_EVIDENCE","FINANCIAL_EVIDENCE","ELECTRONIC_EVIDENCE","MEDICAL_EVIDENCE","COURT_ORDER","LEGAL_NOTICE","ADMISSION"}
_TESTIMONIAL={"WITNESS_STATEMENT"}

def _role(p): return str(p.get("case_role") or "OTHER").upper()
def _text(p): return p.get("raw_text") or p.get("text") or ""

def _attribution(role):
    if role in _ALLEGATION:
        return {"status":"allegation","label":"Allegation / submission","reason":"The source establishes that this proposition was alleged or submitted; it does not independently prove the underlying fact."}
    if role in _TESTIMONIAL:
        return {"status":"testimonial","label":"Witness attribution","reason":"The source supports that a witness made this statement; independent corroboration should be considered separately."}
    if role in _DIRECT:
        return {"status":"direct_evidence","label":"Direct document evidence","reason":"The proposition is supported by documentary/evidentiary material in the uploaded case file."}
    if role=="DENIAL":
        return {"status":"denial","label":"Denial","reason":"The source is a denial and should not be presented as an established fact."}
    return {"status":"uncertain","label":"Attribution uncertain","reason":"The source role does not establish whether the proposition is allegation, testimony, or direct evidence."}

def _strength(status, roles, corroborated, contradicted):
    if status=="unsupported": return "LOW"
    if contradicted:return "DISPUTED"
    direct=sum(r in _DIRECT for r in roles)
    if status=="supported" and (corroborated or direct>=1):return "HIGH"
    if status in {"supported","partially_supported"}:return "MEDIUM"
    return "LOW"

def verify_private_answer(answer, passages):
    private=[p for p in passages if p.get("source_scope","private")=="private"]
    claims=split_claims(answer)
    items=[]
    for claim in claims:
        ranked=sorted(((support_score(claim,_text(p)),p) for p in private),key=lambda z:z[0],reverse=True)
        best=[(s,p) for s,p in ranked if s>=0.22][:3]
        top=best[0][0] if best else 0.0; status=support_status(top)
        sources=[]; roles=[]
        for s,p in best:
            role=_role(p); roles.append(role)
            sources.append({"source_file":p.get("source_file"),"page":p.get("page"),"passage":_text(p),"case_role":role,"role_confidence":p.get("case_role_confidence"),"support_score":s})
        distinct_docs={x.get("source_file") for x in sources if x.get("source_file")}
        corroborated=len(distinct_docs)>=2 and status!="unsupported"
        # Conservative conflict signal: retrieved DENIAL plus a supporting evidentiary/allegation source.
        contradicted=("DENIAL" in roles and any(r!="DENIAL" for r in roles))
        primary_role=roles[0] if roles else "OTHER"
        items.append({"claim":claim,"status":status,"support_score":top,"attribution":_attribution(primary_role),"sources":sources,"corroborated":corroborated,"contradicted":contradicted,"evidence_strength":_strength(status,roles,corroborated,contradicted)})
    supported=sum(x["status"]=="supported" for x in items)
    partial=sum(x["status"]=="partially_supported" for x in items)
    unsupported=sum(x["status"]=="unsupported" for x in items)
    return {"verification_type":"private_evidence","claims":items,"overview":{"claims":len(items),"supported":supported,"partially_supported":partial,"unsupported":unsupported,"corroborated":sum(x["corroborated"] for x in items),"disputed":sum(x["contradicted"] for x in items)}}
