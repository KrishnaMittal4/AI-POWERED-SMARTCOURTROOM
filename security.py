"""
Security helpers for the API: admin-key protection and rate limiting
=====================================================================
Dependency-free (stdlib + FastAPI). Used from main.py as FastAPI dependencies.

ADMIN PROTECTION
    Routes that change or expose server state (upload, delete, feedback
    listing) require the header  X-Admin-Key: <ADMIN_API_KEY>.
    If ADMIN_API_KEY is not set on the server those routes are DISABLED
    (403), so a fresh deploy is closed by default. Wrong keys are throttled
    (ADMIN_MAX_FAILURES per 10 minutes per client) to stop brute forcing.

RATE LIMITING (in-memory, sliding window, per server process)
    Every route that spends Groq quota is limited per client IP and globally:
        RATE_LIMIT_PER_MIN         per IP per minute          (default 6)
        RATE_LIMIT_PER_DAY         per IP per day             (default 100)
        RATE_LIMIT_GLOBAL_PER_MIN  all clients, per minute    (default 12)
        RATE_LIMIT_ENABLED=0       turn everything off (local testing)
    The global cap exists because Groq limits are per ORGANIZATION, not per
    API key: extra keys from the same account do not add quota.
    Limits live in memory, so they reset on restart and are per worker
    process (render.yaml runs one worker, which is what this assumes).

CLIENT IP BEHIND A PROXY (Render / Vercel rewrites)
    TRUST_PROXY_HOPS (default 1) = number of trusted proxies in front of the
    app. The client IP is taken from the RIGHT side of X-Forwarded-For
    (the part the proxy appended), because the left side can be forged by
    the client. Set it to 0 to ignore X-Forwarded-For entirely.
"""
import hmac
import os
import threading
import time
from collections import deque

from fastapi import HTTPException, Request


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def client_ip(request: Request) -> str:
    hops = _int_env("TRUST_PROXY_HOPS", 1)
    if hops > 0:
        xff = request.headers.get("x-forwarded-for", "")
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-min(hops, len(parts))]
    return request.client.host if request.client else "unknown"


class SlidingWindowLimiter:
    """Thread-safe sliding-window counters. `try_acquire` checks ALL the given
    (key, limit, window_seconds) rules first and records a hit on every rule
    only if all of them pass, so a denied request never uses up quota."""

    def __init__(self):
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def try_acquire(self, rules):
        now = time.monotonic()
        with self._lock:
            self._calls += 1
            if self._calls % 2000 == 0:          # drop idle keys so memory stays bounded
                for k in [k for k, q in self._hits.items() if not q or now - q[-1] > 90000]:
                    del self._hits[k]
            worst_wait = 0
            for key, limit, window in rules:
                q = self._hits.setdefault(key, deque())
                while q and now - q[0] >= window:
                    q.popleft()
                if len(q) >= limit:
                    worst_wait = max(worst_wait, int(window - (now - q[0])) + 1)
            if worst_wait:
                return False, worst_wait
            for key, _, _ in rules:
                self._hits[key].append(now)
            return True, 0

    def reset(self):
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def _human(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} seconds"
    if seconds < 5400:
        return f"{round(seconds / 60)} minutes"
    return f"{round(seconds / 3600)} hours"


def rate_limited(scope: str = "llm", per_min: str = "RATE_LIMIT_PER_MIN", per_day: str = "RATE_LIMIT_PER_DAY",
                 default_min: int = 6, default_day: int = 100, use_global: bool = True):
    """FastAPI dependency factory: `Depends(rate_limited())`."""

    def dependency(request: Request):
        if os.getenv("RATE_LIMIT_ENABLED", "1") == "0":
            return
        ip = client_ip(request)
        rules = [
            (f"{scope}:ip:{ip}:min", _int_env(per_min, default_min), 60),
            (f"{scope}:ip:{ip}:day", _int_env(per_day, default_day), 86400),
        ]
        if use_global:
            rules.append((f"{scope}:global:min", _int_env("RATE_LIMIT_GLOBAL_PER_MIN", 12), 60))
        ok, wait = limiter.try_acquire(rules)
        if not ok:
            raise HTTPException(
                status_code=429,
                detail=f"Too many requests. Please try again in {_human(wait)}.",
                headers={"Retry-After": str(wait)},
            )

    return dependency


def require_admin(request: Request):
    """FastAPI dependency protecting admin routes with X-Admin-Key."""
    expected = os.getenv("ADMIN_API_KEY", "")
    if not expected:
        raise HTTPException(
            status_code=403,
            detail="Admin endpoints are disabled on this server (ADMIN_API_KEY is not set).",
        )
    sent = request.headers.get("x-admin-key", "")
    if hmac.compare_digest(sent.encode("utf-8"), expected.encode("utf-8")):
        return
    ok, wait = limiter.try_acquire(
        [(f"adminfail:{client_ip(request)}", _int_env("ADMIN_MAX_FAILURES", 10), 600)]
    )
    if not ok:
        raise HTTPException(
            status_code=429,
            detail=f"Too many failed attempts. Try again in {_human(wait)}.",
            headers={"Retry-After": str(wait)},
        )
    raise HTTPException(status_code=401, detail="Invalid or missing admin key.")
