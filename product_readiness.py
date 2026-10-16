"""LEXAI consolidated product-readiness helpers.
Local/deterministic utilities only: no provider calls and no retrieval changes.
"""
from __future__ import annotations
import os, time
from typing import Any

_STARTED = time.time()

def evidence_strength(citation: dict) -> dict:
    """Derive an explainable evidence score from verification signals.
    This is not legal certainty and never substitutes for precedent treatment.
    """
    score = 0
    reasons, warnings = [], []
    existence = citation.get("existence") or {}
    support = citation.get("passage_support") or {}
    attr = citation.get("attribution") or {}
    if existence.get("exists_in_corpus"):
        score += 15; reasons.append("Judgment exists in the local corpus")
    verdict = support.get("verdict")
    if verdict == "yes": score += 40; reasons.append("Retrieved passage directly supports the claim")
    elif verdict == "partial": score += 22; reasons.append("Retrieved passage partly supports the claim")
    elif verdict in {"no", "disputed"}: warnings.append("Passage support is not established")
    if support.get("agreement") is True: score += 10; reasons.append("Verification providers agree")
    if support.get("independent_provider") is True: score += 8; reasons.append("Independent-provider cross-check completed")
    if attr.get("status") == "supported": score += 17; reasons.append("Speaker attribution matches the passage role")
    elif attr.get("status") == "mismatch": warnings.append("Speaker attribution mismatch")
    elif attr.get("checked"): warnings.append("Speaker attribution is uncertain")
    role = next(iter(attr.get("passage_roles") or []), None)
    if role in {"RATIO", "COURT_REASONING", "FINAL_ORDER"}: score += 10; reasons.append(f"Passage is classified as {role.replace('_',' ').title()}")
    score = max(0, min(100, score))
    level = "high" if score >= 75 else "moderate" if score >= 50 else "low"
    return {"score": score, "level": level, "reasons": reasons, "warnings": warnings,
            "note": "Evidence strength measures source support, not whether later precedent treatment is still good law."}

def verification_overview(citations: list[dict]) -> dict:
    levels = {"high":0,"moderate":0,"low":0}
    contrary = []
    for c in citations:
        es = c.get("evidence_strength") or evidence_strength(c)
        levels[es["level"]] += 1
        if (c.get("passage_support") or {}).get("verdict") in {"no","disputed"} or (c.get("attribution") or {}).get("status") == "mismatch":
            contrary.append({"case_name":c.get("case_name"),"reason":"Support or attribution requires review"})
    return {"authority_count":len(citations),"evidence_levels":levels,"review_authorities":contrary}

def runtime_diagnostics(records_count: int, provider_status: dict[str, Any]) -> dict:
    return {"uptime_seconds":int(time.time()-_STARTED),"chunks_indexed":records_count,
            "providers":provider_status,"retrieval_strategy":os.getenv("RAG_RETRIEVAL_STRATEGY","adaptive"),
            "version":"deployment-private-rag-final"}
