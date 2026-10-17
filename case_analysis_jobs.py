"""Lightweight in-process Case Intelligence jobs for single-instance/demo deployments.

This avoids holding the browser request open while Gemini/Groq and Supabase work.
No private case text is stored in job metadata.
"""
from __future__ import annotations

import threading, time, uuid
from concurrent.futures import ThreadPoolExecutor

_jobs = {}
_lock = threading.RLock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="case-intel")


def _now():
    return int(time.time())


def _set(job_id, **updates):
    with _lock:
        job = _jobs.get(job_id)
        if job:
            job.update(updates)
            job["updated_at"] = _now()


def start(user_id, case_id, fn):
    job_id = uuid.uuid4().hex
    job = {
        "job_id": job_id, "user_id": str(user_id), "case_id": str(case_id),
        "status": "queued", "stage": "queued", "message": "Analysis queued",
        "created_at": _now(), "updated_at": _now(), "result": None, "error": None,
    }
    with _lock:
        _jobs[job_id] = job

    def progress(stage, message=None):
        _set(job_id, status="processing", stage=stage, message=message or stage.replace("_", " ").title())

    def runner():
        try:
            progress("preparing_documents", "Preparing private case documents")
            result = fn(progress)
            _set(job_id, status="completed", stage="completed", message="Case Intelligence ready", result=result)
        except Exception as exc:
            detail = getattr(exc, "detail", None)
            if isinstance(detail, dict):
                message = detail.get("message") or detail.get("detail") or str(detail)
                code = detail.get("code") or "analysis_failed"
                retryable = bool(detail.get("retryable", True))
            else:
                message = str(detail or exc) or "Case Intelligence failed"
                code = "analysis_failed"
                retryable = True
            _set(job_id, status="failed", stage="failed", message=message,
                 error={"code": code, "message": message, "retryable": retryable})

    _executor.submit(runner)
    return {k: v for k, v in job.items() if k not in {"user_id"}}


def get(user_id, case_id, job_id):
    with _lock:
        job = _jobs.get(job_id)
        if not job or job.get("user_id") != str(user_id) or job.get("case_id") != str(case_id):
            return None
        return {k: v for k, v in job.items() if k != "user_id"}
