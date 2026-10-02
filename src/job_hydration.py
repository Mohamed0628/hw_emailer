"""Hydrate legacy alerts through public ATS posting feeds.

Discovery/verification uses public read-only posting interfaces. Application
submission remains browser-driven and subject to the existing safety policy.
"""
from __future__ import annotations

import html
import json
import re
import ssl
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .identity import canonical_url, detect_ats, requisition
from .models import Job

_MAX_BYTES = 4_000_000


@dataclass
class HydrationResult:
    job: Job
    status: str  # verified | closed | temporary_failure | manual
    reason: str = ""


def _json_get(url: str, *, timeout: float) -> tuple[dict | list | None, int]:
    req = Request(url, headers={"Accept": "application/json",
                                "User-Agent": "hw-emailer/1.0"})
    # Prefer certifi when installed; otherwise use the platform trust store.
    try:
        import certifi
        context = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        context = ssl.create_default_context()
    try:
        with urlopen(req, timeout=timeout, context=context) as response:
            raw = response.read(_MAX_BYTES + 1)
            if len(raw) > _MAX_BYTES:
                return None, 413
            return json.loads(raw.decode(response.headers.get_content_charset() or "utf-8")), response.status
    except HTTPError as exc:
        return None, exc.code
    except (URLError, TimeoutError, OSError, json.JSONDecodeError):
        return None, 0


def _parts(job: Job) -> tuple[str, list[str]]:
    url = urlsplit(job.application_url or job.url)
    return (url.hostname or "").lower(), [p for p in url.path.split("/") if p]


def _description(value) -> str:
    # Preserve useful words for scoring while removing markup noise.
    text = html.unescape(str(value or ""))
    return re.sub(r"<[^>]+>", " ", text)


def _verified(job: Job, *, ats: str, description: str, application_url: str,
              location: str | None = None, req: str | None = None) -> HydrationResult:
    locations = job.locations or ([location] if location else [])
    return HydrationResult(job.model_copy(update={
        "description": description or job.description,
        "application_url": application_url,
        "ats": ats,
        "provider": job.provider or ats,
        "locations": locations,
        "requisition_id": req or job.requisition_id,
        "active": True,
    }), "verified")


def _greenhouse(job: Job, timeout: float) -> HydrationResult:
    _, parts = _parts(job)
    # job-boards.greenhouse.io/{board}/jobs/{id}
    try:
        board = parts[0]
        job_id = str(requisition(job) or "")
    except IndexError:
        board, job_id = "", ""
    if not board or not job_id:
        return HydrationResult(job, "temporary_failure", "could not parse Greenhouse board/job id")
    data, status = _json_get(
        f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}", timeout=timeout)
    if status in {404, 410}:
        return HydrationResult(job.model_copy(update={"active": False}), "closed",
                               f"Greenhouse posting returned HTTP {status}")
    if status != 200 or not isinstance(data, dict):
        return HydrationResult(job, "temporary_failure", "Greenhouse public API unavailable")
    return _verified(job, ats="greenhouse", description=_description(data.get("content")),
                     application_url=data.get("absolute_url") or canonical_url(job.url),
                     location=(data.get("location") or {}).get("name"),
                     req=str(data.get("id") or job_id))


def _lever(job: Job, timeout: float) -> HydrationResult:
    host, parts = _parts(job)
    if len(parts) < 2:
        return HydrationResult(job, "temporary_failure", "could not parse Lever site/posting id")
    site, posting_id = parts[0], parts[1]
    api_host = "api.eu.lever.co" if host.endswith("eu.lever.co") else "api.lever.co"
    data, status = _json_get(
        f"https://{api_host}/v0/postings/{site}/{posting_id}?mode=json", timeout=timeout)
    if status in {404, 410}:
        return HydrationResult(job.model_copy(update={"active": False}), "closed",
                               f"Lever posting returned HTTP {status}")
    if status != 200 or not isinstance(data, dict):
        return HydrationResult(job, "temporary_failure", "Lever public API unavailable")
    desc = " ".join(str(data.get(k) or "") for k in
                    ("descriptionPlain", "description", "additionalPlain", "additional"))
    categories = data.get("categories") or {}
    return _verified(job, ats="lever", description=_description(desc),
                     application_url=data.get("applyUrl") or data.get("hostedUrl") or canonical_url(job.url),
                     location=categories.get("location"), req=str(data.get("id") or posting_id))


def _ashby(job: Job, timeout: float) -> HydrationResult:
    _, parts = _parts(job)
    if len(parts) < 2:
        return HydrationResult(job, "temporary_failure", "could not parse Ashby board/posting")
    board = parts[0]
    target = canonical_url(job.url)
    data, status = _json_get(
        f"https://api.ashbyhq.com/posting-api/job-board/{board}", timeout=timeout)
    if status in {404, 410}:
        return HydrationResult(job.model_copy(update={"active": False}), "closed",
                               f"Ashby board returned HTTP {status}")
    if status != 200 or not isinstance(data, dict):
        return HydrationResult(job, "temporary_failure", "Ashby public posting API unavailable")
    jobs = data.get("jobs") or []
    match = next((x for x in jobs if canonical_url(str(x.get("jobUrl") or "")) == target), None)
    if match is None:
        target_id = parts[-1]
        match = next((x for x in jobs if target_id and target_id in str(x.get("jobUrl") or "")), None)
    if match is None:
        return HydrationResult(job.model_copy(update={"active": False}), "closed",
                               "posting absent from Ashby public job board")
    desc = match.get("descriptionPlain") or match.get("description") or ""
    return _verified(job, ats="ashby", description=_description(desc),
                     application_url=match.get("applyUrl") or match.get("jobUrl") or job.url,
                     location=match.get("location"))


def hydrate_job(job: Job, *, timeout: float = 12.0) -> HydrationResult:
    ats = detect_ats(job.application_url or job.url)
    if ats == "workday":
        return HydrationResult(job, "manual", "Workday remains manual-only")
    if ats == "greenhouse":
        return _greenhouse(job, timeout)
    if ats == "lever":
        return _lever(job, timeout)
    if ats == "ashby":
        return _ashby(job, timeout)
    return HydrationResult(job, "manual", "unsupported ATS remains manual")
