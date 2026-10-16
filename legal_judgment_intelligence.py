"""Deterministic legal-role intelligence for judgment passages.

V4.3 intentionally uses local, explainable heuristics: no LLM/API call is
required during ingestion or retrieval.  The role is metadata, not a claim of
legal truth; low-confidence passages remain MIXED/UNKNOWN.
"""
import re
from typing import Dict, List

ROLES = (
    "FACTS", "PROCEDURAL_HISTORY", "PETITIONER_ARGUMENT",
    "RESPONDENT_ARGUMENT", "STATUTORY_PROVISION", "PRECEDENT",
    "COURT_REASONING", "RATIO", "OBITER", "FINAL_ORDER", "MIXED", "UNKNOWN",
)

_PATTERNS = {
    "FINAL_ORDER": [r"\bappeal (?:is )?(?:allowed|dismissed)\b", r"\bpetition (?:is )?(?:allowed|dismissed)\b", r"\bwe (?:therefore )?(?:allow|dismiss|dispose)\b", r"\border(?:ed)? accordingly\b", r"\bno order as to costs\b"],
    "RATIO": [r"\bwe hold that\b", r"\bwe therefore hold\b", r"\bit is settled (?:law|principle)\b", r"\bthe legal position is\b", r"\bwe conclude that\b"],
    "COURT_REASONING": [r"\bin our (?:view|opinion|considered opinion)\b", r"\bwe are of the (?:view|opinion)\b", r"\bwe find that\b", r"\bwe are unable to accept\b", r"\bthe court finds\b", r"\btherefore\b", r"\bthus\b"],
    "PETITIONER_ARGUMENT": [r"\blearned counsel for (?:the )?(?:petitioner|appellant)\b", r"\bpetitioner(?:'s)? counsel\b", r"\bappellant(?:s)? (?:submitted|contended|argued|urged)\b"],
    "RESPONDENT_ARGUMENT": [r"\blearned counsel for (?:the )?respondent\b", r"\brespondent(?:s)? (?:submitted|contended|argued|urged)\b", r"\bcounsel for the respondent\b"],
    "STATUTORY_PROVISION": [r"\bsection\s+\d+[a-z]?(?:\s*\([^)]*\))*\b", r"\barticle\s+\d+[a-z]?(?:\s*\([^)]*\))*\b", r"\bunder the .*? act\b", r"\bstatutory provision\b"],
    "PRECEDENT": [r"\b(?:relied on|relied upon|referred to|cited)\b.{0,80}\bv\.?s?\.?\b", r"\bin .*? v\.?s?\.? .*?(?:this court|court)\b", r"\bprecedent\b", r"\bearlier decision\b"],
    "PROCEDURAL_HISTORY": [r"\btrial court\b", r"\bhigh court\b.{0,80}\b(?:allowed|dismissed|affirmed|reversed)\b", r"\bfiled (?:an )?(?:appeal|petition|writ)\b", r"\bimpugned (?:order|judgment)\b", r"\bprocedural history\b"],
    "FACTS": [r"\bthe facts (?:are|of the case)\b", r"\bbrief facts\b", r"\bfactual matrix\b", r"\bcase of the prosecution\b", r"\bon \d{1,2}(?:st|nd|rd|th)?\b", r"\bthereafter\b"],
    "OBITER": [r"\bobiter\b", r"\bby way of observation\b", r"\bwe may observe\b", r"\bwe may add\b"],
}

_PRIORITY = ["FINAL_ORDER", "RATIO", "PETITIONER_ARGUMENT", "RESPONDENT_ARGUMENT", "COURT_REASONING", "OBITER", "PRECEDENT", "PROCEDURAL_HISTORY", "STATUTORY_PROVISION", "FACTS"]

def classify_legal_role(text: str) -> Dict:
    t = (text or "").strip()
    if not t:
        return {"role": "UNKNOWN", "confidence": 0.0, "signals": []}
    low = t.lower()
    scores = {}
    signals = {}
    for role, pats in _PATTERNS.items():
        hits = [p for p in pats if re.search(p, low, flags=re.I | re.S)]
        if hits:
            scores[role] = len(hits)
            signals[role] = hits[:3]
    if not scores:
        return {"role": "MIXED", "confidence": 0.35, "signals": []}
    best_score = max(scores.values())
    tied = [r for r, s in scores.items() if s == best_score]
    best = next((r for r in _PRIORITY if r in tied), tied[0])
    second = sorted(scores.values(), reverse=True)[1] if len(scores) > 1 else 0
    confidence = min(0.95, 0.55 + 0.12 * best_score + (0.08 if best_score > second else 0.0))
    if len(tied) >= 3 and best_score == 1:
        # Multiple court-voice signals are mutually reinforcing rather than
        # contradictory (e.g. "we therefore hold ... appeal is allowed").
        court_voice = {"FINAL_ORDER", "RATIO", "COURT_REASONING", "OBITER"}
        if set(tied).issubset(court_voice):
            return {"role": best, "confidence": 0.78, "signals": [x for r in tied for x in signals.get(r, [])][:3]}
        return {"role": "MIXED", "confidence": 0.45, "signals": [x for r in tied for x in signals.get(r, [])][:3]}
    return {"role": best, "confidence": round(confidence, 3), "signals": signals.get(best, [])}

def annotate_record(record: dict) -> dict:
    if record.get("legal_role"):
        return record
    info = classify_legal_role(record.get("raw_text") or record.get("text") or "")
    record["legal_role"] = info["role"]
    record["legal_role_confidence"] = info["confidence"]
    record["legal_role_signals"] = info["signals"]
    return record

def preferred_roles_for_query(query: str) -> List[str]:
    q = (query or "").lower()
    if re.search(r"\b(?:held|holding|ratio|ratio decidendi|what did .* court decide|court hold)\b", q):
        return ["RATIO", "COURT_REASONING", "FINAL_ORDER"]
    if re.search(r"\b(?:final order|outcome|disposed|allowed|dismissed|relief granted)\b", q):
        return ["FINAL_ORDER", "COURT_REASONING"]
    if re.search(r"\b(?:argument|submission|contend|counsel|petitioner|appellant|respondent)\b", q):
        return ["PETITIONER_ARGUMENT", "RESPONDENT_ARGUMENT"]
    if re.search(r"\b(?:section|article|statute|provision|act\b)\b", q):
        return ["STATUTORY_PROVISION", "COURT_REASONING", "RATIO"]
    if re.search(r"\b(?:precedent|authority|case law|judgment|decision)\b", q):
        return ["PRECEDENT", "COURT_REASONING", "RATIO"]
    if re.search(r"\b(?:facts|factual|what happened|incident)\b", q):
        return ["FACTS", "PROCEDURAL_HISTORY"]
    return []
