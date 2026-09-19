"""Hydrate legacy alert records from their canonical posting before evaluation."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .identity import canonical_url, detect_ats
from .models import Job

_MAX_BYTES = 2_000_000


@dataclass
class HydrationResult:
    job: Job
    status: str
    reason: str = ""


def _closed_status(code: int) -> bool:
    return code in {404, 410}


def hydrate_job(job: Job, *, timeout: float = 12.0) -> HydrationResult:
    """Fetch an official ATS page and attach page text for legacy alert records.

    Fail closed: network errors/redirects away from the recognized ATS never
    authorize automatic application. Workday is left manual and unfetched.
    """
    ats = detect_ats(job.application_url or job.url)
    if ats == "workday":
        return HydrationResult(job, "manual", "Workday remains manual-only")
    if ats not in {"greenhouse", "lever", "ashby"}:
        return HydrationResult(job.model_copy(update={"active": False}), "blocked",
                               "unverified or unsupported application host")

    url = canonical_url(job.application_url or job.url)
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 hw-emailer/1.0"})
    try:
        with urlopen(req, timeout=timeout) as response:
            final_url = response.geturl()
            final_ats = detect_ats(final_url)
            if final_ats != ats:
                return HydrationResult(job.model_copy(update={"active": False}), "blocked",
                                       "posting redirected away from verified ATS")
            raw = response.read(_MAX_BYTES + 1)
            if len(raw) > _MAX_BYTES:
                return HydrationResult(job.model_copy(update={"active": False}), "blocked",
                                       "posting response exceeded hydration limit")
            text = raw.decode(response.headers.get_content_charset() or "utf-8", errors="replace")
    except HTTPError as exc:
        if _closed_status(exc.code):
            return HydrationResult(job.model_copy(update={"active": False}), "closed",
                                   f"posting returned HTTP {exc.code}")
        return HydrationResult(job.model_copy(update={"active": False}), "blocked",
                               f"posting verification returned HTTP {exc.code}")
    except (URLError, TimeoutError, OSError) as exc:
        return HydrationResult(job.model_copy(update={"active": False}), "blocked",
                               "posting verification failed: " + type(exc).__name__)

    lowered = text.lower()
    closed_phrases = ("job not found", "no longer accepting", "position has been filled",
                      "applications are closed", "posting is closed")
    if any(p in lowered[:100000] for p in closed_phrases):
        return HydrationResult(job.model_copy(update={"active": False}), "closed",
                               "posting page indicates the role is closed")

    # HTML is intentionally retained as description input: the existing scoring
    # tokenizer extracts technical terms without requiring a new parser dependency.
    hydrated = job.model_copy(update={
        "url": canonical_url(final_url),
        "application_url": canonical_url(final_url),
        "ats": ats,
        "provider": job.provider or ats,
        "description": text,
        "active": True,
    })
    return HydrationResult(hydrated, "verified")
