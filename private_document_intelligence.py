"""Deterministic private-case document intelligence.
Keeps case evidence semantics separate from judgment roles such as ratio/obiter.
"""
from __future__ import annotations
import re

ROLES = {
    "CASE_FACT", "ALLEGATION", "ADMISSION", "DENIAL", "WITNESS_STATEMENT",
    "DOCUMENTARY_EVIDENCE", "ELECTRONIC_EVIDENCE", "FINANCIAL_EVIDENCE",
    "MEDICAL_EVIDENCE", "LEGAL_NOTICE", "POLICE_RECORD", "PROCEDURAL_EVENT",
    "COURT_ORDER", "PARTY_SUBMISSION", "DATE_EVENT", "OTHER"
}

def classify_private_passage(text: str, filename: str = "") -> dict:
    t=(text or "").lower(); f=(filename or "").lower()
    scores={r:0 for r in ROLES}
    def hit(role, pats, weight=1):
        for p in pats:
            if re.search(p,t) or re.search(p,f): scores[role]+=weight
    hit("LEGAL_NOTICE", [r"legal notice", r"demand notice", r"notice dated"], 3)
    hit("POLICE_RECORD", [r"\bfir\b", r"first information report", r"charge.?sheet", r"police station", r"investigating officer"], 3)
    hit("WITNESS_STATEMENT", [r"witness", r"statement under", r"deposed", r"i saw", r"i heard"], 2)
    hit("FINANCIAL_EVIDENCE", [r"bank statement", r"transaction", r"account no", r"cheque", r"amount of", r"₹|rs\.?\s?\d"], 2)
    hit("ELECTRONIC_EVIDENCE", [r"cctv", r"email", r"whatsapp", r"call detail", r"electronic record", r"metadata"], 2)
    hit("MEDICAL_EVIDENCE", [r"medical report", r"post.?mortem", r"doctor", r"injury", r"hospital"], 2)
    hit("COURT_ORDER", [r"ordered accordingly", r"petition is allowed", r"petition is dismissed", r"court order", r"order dated"], 3)
    hit("ALLEGATION", [r"alleged", r"complainant stated", r"accused of", r"it is alleged", r"complaint"], 2)
    hit("ADMISSION", [r"admitted that", r"admits that", r"admission"], 3)
    hit("DENIAL", [r"denied that", r"denies that", r"denial"], 3)
    hit("PARTY_SUBMISSION", [r"submitted that", r"contended that", r"counsel for", r"learned counsel"], 2)
    hit("PROCEDURAL_EVENT", [r"filed on", r"hearing", r"summons", r"bail", r"arrested", r"investigation", r"proceedings"], 1)
    hit("DATE_EVENT", [r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", r"\b\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\b"], 1)
    hit("DOCUMENTARY_EVIDENCE", [r"agreement", r"receipt", r"certificate", r"document", r"memo", r"invoice"], 1)
    best=max(scores,key=scores.get); top=scores[best]
    if top<=0: best="CASE_FACT" if len(t)>80 else "OTHER"
    ordered=sorted(scores.values(),reverse=True); second=ordered[1] if len(ordered)>1 else 0
    conf=0.55 if top<=1 else min(0.95,0.62+0.09*top)
    if top and second==top: conf=min(conf,0.68)
    return {"case_role":best,"case_role_confidence":round(conf,2)}

def preferred_private_roles(question: str) -> set[str]:
    q=(question or "").lower()
    if any(x in q for x in ["witness", "statement", "testimony"]): return {"WITNESS_STATEMENT"}
    if any(x in q for x in ["financial", "payment", "bank", "amount", "cheque"]): return {"FINANCIAL_EVIDENCE","DOCUMENTARY_EVIDENCE"}
    if any(x in q for x in ["notice", "demand"]): return {"LEGAL_NOTICE"}
    if any(x in q for x in ["order", "court directed", "court held"]): return {"COURT_ORDER","PROCEDURAL_EVENT"}
    if any(x in q for x in ["allegation", "accused of", "complaint says"]): return {"ALLEGATION","POLICE_RECORD"}
    if any(x in q for x in ["cctv", "email", "whatsapp", "electronic"]): return {"ELECTRONIC_EVIDENCE"}
    if any(x in q for x in ["medical", "injury", "doctor"]): return {"MEDICAL_EVIDENCE"}
    if any(x in q for x in ["timeline", "when", "date", "after", "before"]): return {"DATE_EVENT","PROCEDURAL_EVENT"}
    return set()


def detect_document_policy(text: str, filename: str = "") -> dict:
    """Conservatively detect whether a private upload is itself a judgment/order.

    The file remains private; this only selects the verification semantics.
    """
    t=(text or "").lower(); f=(filename or "").lower()
    score=0
    if re.search(r"\b(judg(e)?ment|judgment|court order|order)\b", f): score += 2
    signals=[
        r"\bin the (supreme court|high court|court of)\b",
        r"\bcoram\b", r"\bjudg(e)?ment\b", r"\bwe (therefore )?hold\b",
        r"\bappeal (is )?(allowed|dismissed)\b", r"\bpetition (is )?(allowed|dismissed)\b",
        r"\bordered accordingly\b", r"\bfor the foregoing reasons\b"
    ]
    score += sum(1 for pat in signals if re.search(pat,t))
    policy='judgment' if score >= 3 else 'private_evidence'
    return {'document_policy':policy,'document_policy_confidence':round(min(.97,.55+.08*score),2) if score else .55}
