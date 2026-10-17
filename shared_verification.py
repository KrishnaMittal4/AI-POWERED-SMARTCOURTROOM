"""Shared, provider-free verification primitives used by judgment and private evidence policies."""
import re

_STOP={"the","a","an","and","or","of","to","in","on","for","is","are","was","were","be","been","that","this","with","as","by","from","at","it","its"}

def tokens(text):
    return {x for x in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(x)>2 and x not in _STOP}

def support_score(claim, passage):
    c=tokens(claim); p=tokens(passage)
    if not c or not p:return 0.0
    return round(len(c&p)/max(1,len(c)),3)

def support_status(score):
    if score>=0.58:return "supported"
    if score>=0.30:return "partially_supported"
    return "unsupported"

def split_claims(answer, max_claims=8):
    raw=re.split(r"(?<=[.!?])\s+|\n+", answer or "")
    out=[]
    for x in raw:
        x=x.strip(" -*\t")
        if len(x)>=28 and x not in out: out.append(x)
        if len(out)>=max_claims:break
    return out
