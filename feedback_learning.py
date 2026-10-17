"""Bounded feedback learning for LEXAI retrieval.

This is intentionally a contextual-bandit style adjustment layer, not LLM
fine-tuning.  It learns small query-type and source priors from explicit user
feedback.  Verification remains independent and can never be overridden by a
learned reward.
"""
from __future__ import annotations
import math, os, re

MAX_WEIGHT_DELTA = float(os.getenv("FEEDBACK_MAX_WEIGHT_DELTA", "0.12"))
MAX_SOURCE_BONUS = float(os.getenv("FEEDBACK_MAX_SOURCE_BONUS", "0.0015"))
MIN_EVENTS = int(os.getenv("FEEDBACK_MIN_EVENTS", "3"))


def query_type(query: str) -> str:
    q=(query or "").lower()
    if re.search(r"\b(section|article|sec\.?|s\.)\s*\d", q) or re.search(r"\b(ipc|crpc|bnss|bns|evidence act|negotiable instruments|constitution)\b", q):
        return "statutory"
    if re.search(r"\b(precedent|authority|rely on|case law|support my case)\b", q):
        return "advocate"
    if re.search(r"\b(why|whether|when can|can a|principle|meaning|interpret|legal issue)\b", q):
        return "semantic"
    return "mixed"


def bounded_delta(up: int, down: int, scale: float = MAX_WEIGHT_DELTA) -> float:
    total=max(0,int(up))+max(0,int(down))
    if total < MIN_EVENTS: return 0.0
    # Bayesian smoothing + confidence growth; deliberately small.
    preference=((up+1.0)/(total+2.0)-0.5)*2.0
    confidence=min(1.0, math.log1p(total)/math.log(21.0))
    return max(-scale,min(scale,preference*confidence*scale))


def profile_adjustment(query: str) -> dict:
    """Return bounded retrieval adjustment learned from stored feedback."""
    try:
        from feedback_store import feedback_learning_stats
        stats=feedback_learning_stats(query_type(query))
    except Exception:
        stats={}
    delta=bounded_delta(stats.get("up",0),stats.get("down",0))
    # Positive satisfaction gently favors semantic/dense evidence; negative
    # satisfaction gently favors lexical evidence. This never exceeds 12%.
    return {
        "query_type": query_type(query),
        "dense_multiplier": 1.0 + delta,
        "bm25_multiplier": 1.0 - delta,
        "events": int(stats.get("total",0) or 0),
        "reward_mean": float(stats.get("reward_mean",0.0) or 0.0),
        "bounded_delta": delta,
    }


def source_bonus(query: str, source_file: str | None) -> float:
    if not source_file: return 0.0
    try:
        from feedback_store import source_learning_stats
        s=source_learning_stats(query_type(query),source_file)
    except Exception:
        return 0.0
    total=int(s.get("total",0) or 0)
    if total < MIN_EVENTS: return 0.0
    net=(float(s.get("positive",0))-float(s.get("negative",0)))/max(1,total)
    confidence=min(1.0, math.log1p(total)/math.log(21.0))
    return max(-MAX_SOURCE_BONUS,min(MAX_SOURCE_BONUS,net*confidence*MAX_SOURCE_BONUS))
