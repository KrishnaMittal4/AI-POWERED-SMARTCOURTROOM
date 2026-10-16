"""Central provider/model routing for LEXAI.

Keeps Gemini/Groq model IDs, retries and truthful provider metadata in one place.
Gemini is preferred for independent verification/structured extraction and judicial
reasoning; Groq is the resilience fallback when a Groq client is supplied.
"""
from __future__ import annotations

import os
import random
import time
from typing import Optional, Any

GEMINI_VERIFY_MODEL = os.getenv("GEMINI_VERIFY_MODEL", "gemini-3.5-flash-lite")
GEMINI_EXTRACTION_MODEL = os.getenv("GEMINI_EXTRACTION_MODEL", "gemini-3.5-flash-lite")
GEMINI_REASONING_MODEL = os.getenv("GEMINI_REASONING_MODEL", "gemini-3.8-flash")
GROQ_PRIMARY_MODEL = os.getenv("GROQ_PRIMARY_MODEL", "qwen/qwen3.8-27b")
GROQ_FALLBACK_MODEL = os.getenv("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")
GROQ_VERIFY_MODEL = os.getenv("GROQ_VERIFY_MODEL", "openai/gpt-oss-20b")
GROQ_SECONDARY_VERIFY_MODEL = os.getenv("GROQ_SECONDARY_VERIFY_MODEL", "openai/gpt-oss-120b")

# Feature-specific output budgets. Keep Groq below common free/on-demand OTPM ceilings.
TASK_TOKEN_BUDGETS = {
    "advocate": int(os.getenv("TOKENS_ADVOCATE", "900")),
    "citizen": int(os.getenv("TOKENS_CITIZEN", "750")),
    "moot": int(os.getenv("TOKENS_MOOT", "700")),
    "moot_short": int(os.getenv("TOKENS_MOOT_SHORT", "500")),
    "case_intelligence": int(os.getenv("TOKENS_CASE_INTELLIGENCE", "950")),
    "issue_map": int(os.getenv("TOKENS_ISSUE_MAP", "700")),
    "verification": int(os.getenv("TOKENS_VERIFICATION", "500")),
    "general": int(os.getenv("TOKENS_GENERAL", "900")),
}

TASK_PRIMARY = {
    "moot": "gemini", "moot_short": "gemini",
    "case_intelligence": "gemini", "issue_map": "gemini",
    "advocate": "groq", "citizen": "groq", "verification": "groq", "general": "groq",
}

_TRANSIENT = (
    "429", "500", "502", "503", "504", "unavailable", "high demand",
    "resource_exhausted", "rate limit", "rate_limit", "timeout", "temporarily",
    "deadline exceeded", "internal",
)


def is_transient_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _TRANSIENT)


def gemini_configured() -> bool:
    return bool(os.getenv("GEMINI_API_KEY"))


def provider_status() -> dict:
    """Configuration health only: never burns provider quota just to render /health."""
    gemini_sdk = True
    gemini_sdk_error = None
    try:
        from google import genai  # noqa: F401
    except Exception as exc:
        gemini_sdk = False
        gemini_sdk_error = str(exc)
    return {
        "gemini": {
            "configured": gemini_configured(),
            "sdk_available": gemini_sdk,
            "sdk_error": gemini_sdk_error,
            "verify_model": GEMINI_VERIFY_MODEL,
            "extraction_model": GEMINI_EXTRACTION_MODEL,
            "reasoning_model": GEMINI_REASONING_MODEL,
        },
        "groq": {
            "configured": bool(os.getenv("GROQ_API_KEY")),
            "primary_model": GROQ_PRIMARY_MODEL,
            "fallback_model": GROQ_FALLBACK_MODEL,
        },
    }


def call_gemini(
    prompt: str,
    *,
    purpose: str = "verify",
    attempts: int = 3,
    base_delays: tuple[float, ...] = (0.0, 1.0, 3.0),
    max_tokens: int | None = None,
    temperature: float = 0.0,
) -> dict:
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return {"ok": False, "provider": "gemini", "error": "GEMINI_API_KEY not set", "attempts": 0}

    model = {
        "verify": GEMINI_VERIFY_MODEL,
        "extract": GEMINI_EXTRACTION_MODEL,
        "reason": GEMINI_REASONING_MODEL,
    }.get(purpose, GEMINI_VERIFY_MODEL)

    try:
        from google import genai
        client = genai.Client(api_key=key)
    except Exception as exc:
        return {"ok": False, "provider": "gemini", "model": model, "error": f"Gemini SDK/configuration unavailable: {exc}", "attempts": 0}

    last_error = "Gemini call failed"
    n = max(1, min(attempts, len(base_delays)))
    for idx in range(n):
        delay = base_delays[idx]
        if delay:
            # small jitter prevents several concurrent citation checks retrying together
            time.sleep(delay + random.uniform(0.0, 0.35))
        try:
            
            kwargs = {"model": model, "contents": prompt}
            if max_tokens is not None:
                try:
                    from google.genai import types
                    kwargs["config"] = types.GenerateContentConfig(max_output_tokens=max_tokens, temperature=temperature)
                except Exception:
                    pass
            response = client.models.generate_content(**kwargs)
            text = (getattr(response, "text", None) or "").strip()
            if text:
                return {"ok": True, "text": text, "provider": "gemini", "model": model, "attempts": idx + 1, "independent_provider": True}
            last_error = "Gemini returned an empty response"
        except Exception as exc:
            last_error = str(exc)
            if not is_transient_error(exc):
                break
    return {"ok": False, "provider": "gemini", "model": model, "error": last_error, "attempts": idx + 1, "independent_provider": False}


def call_groq(
    client: Any,
    prompt: str,
    *,
    system_prompt: str | None = None,
    models: Optional[list[str]] = None,
    max_tokens: int = 1800,
    temperature: float = 0.0,
) -> dict:
    if client is None:
        return {"ok": False, "provider": "groq", "error": "Groq client unavailable"}
    model_list = models or [GROQ_PRIMARY_MODEL, GROQ_FALLBACK_MODEL]
    last_error = "Groq call failed"
    for model in model_list:
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            safe_tokens = min(int(max_tokens), int(os.getenv("GROQ_MAX_OUTPUT_TOKENS", "900")))
            resp = client.chat.completions.create(
                model=model, messages=messages, temperature=temperature, max_tokens=safe_tokens,
            )
            text = (resp.choices[0].message.content or "").strip()
            if text:
                return {"ok": True, "text": text, "provider": "groq", "model": model, "attempts": 1, "independent_provider": False}
            last_error = f"{model} returned an empty response"
        except Exception as exc:
            last_error = str(exc)
    return {"ok": False, "provider": "groq", "error": last_error, "model": model_list[-1], "independent_provider": False}


def gemini_then_groq(
    prompt: str,
    *,
    purpose: str,
    groq_client: Any = None,
    system_prompt: str | None = None,
    groq_models: Optional[list[str]] = None,
    max_tokens: int = 1800,
    temperature: float = 0.0,
) -> dict:
    gemini = call_gemini(prompt if not system_prompt else f"{system_prompt}\n\n---\n\n{prompt}", purpose=purpose, max_tokens=max_tokens, temperature=temperature)
    if gemini.get("ok"):
        return gemini
    groq = call_groq(groq_client, prompt, system_prompt=system_prompt, models=groq_models, max_tokens=max_tokens, temperature=temperature)
    groq["fallback_reason"] = gemini.get("error")
    groq["gemini_attempts"] = gemini.get("attempts", 0)
    groq["resilience_fallback"] = bool(groq.get("ok"))
    return groq


def route_task(
    task: str, prompt: str, *, groq_client: Any = None, system_prompt: str | None = None,
    purpose: str | None = None, temperature: float = 0.1, max_tokens: int | None = None,
) -> dict:
    """Task-aware Groq/Gemini routing with cross-provider fallback and truthful metadata."""
    task = (task or "general").lower()
    budget = int(max_tokens or TASK_TOKEN_BUDGETS.get(task, 800))
    primary = TASK_PRIMARY.get(task, "groq")
    gem_purpose = purpose or ("extract" if task in {"case_intelligence", "issue_map"} else "reason")
    combined = prompt if not system_prompt else f"{system_prompt}\n\n---\n\n{prompt}"
    errors = []
    started = time.time()
    if primary == "gemini":
        first = call_gemini(combined, purpose=gem_purpose, max_tokens=budget, temperature=temperature)
        if first.get("ok"):
            first.update({"task": task, "primary_provider": "gemini", "fallback_used": False, "token_budget": budget, "latency_ms": round((time.time()-started)*1000,1)})
            return first
        errors.append(f"Gemini: {first.get('error')}")
        second = call_groq(groq_client, prompt, system_prompt=system_prompt, max_tokens=budget, temperature=temperature)
    else:
        first = call_groq(groq_client, prompt, system_prompt=system_prompt, max_tokens=budget, temperature=temperature)
        if first.get("ok"):
            first.update({"task": task, "primary_provider": "groq", "fallback_used": False, "token_budget": budget, "latency_ms": round((time.time()-started)*1000,1)})
            return first
        errors.append(f"Groq: {first.get('error')}")
        second = call_gemini(combined, purpose=gem_purpose, max_tokens=budget, temperature=temperature)
    if second.get("ok"):
        second.update({"task": task, "primary_provider": primary, "fallback_used": True, "fallback_reason": errors[-1], "token_budget": budget, "latency_ms": round((time.time()-started)*1000,1)})
        return second
    errors.append(f"{second.get('provider','fallback')}: {second.get('error')}")
    return {"ok": False, "task": task, "primary_provider": primary, "fallback_used": True, "token_budget": budget, "error": " | ".join(errors), "latency_ms": round((time.time()-started)*1000,1)}
