"""Stable requisition identities, without invalidating legacy job IDs."""
from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .models import Job, normalize_title

HOSTS = {
    "greenhouse": ("greenhouse.io",),
    "lever": ("lever.co",),
    "ashby": ("ashbyhq.com",),
    "workday": ("myworkdayjobs.com", "myworkdaysite.com"),
    "icims": ("icims.com",),
    "smartrecruiters": ("smartrecruiters.com",),
}


def detect_ats(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower()
    return next((ats for ats, domains in HOSTS.items()
                 if any(host == d or host.endswith("." + d) for d in domains)), None)


WORKDAY_MANUAL_REASON = "Application: Manual — Workday"


def is_workday_job(job: Job) -> bool:
    """Deny automation on ANY Workday evidence; conflicting metadata cannot opt in.

    This is deliberately independent of scores, modes, adapters and configuration.
    Inspect both links so an alternate application URL cannot erase provenance.
    """
    return (any((value or "").strip().casefold() == "workday"
                for value in (job.ats, job.provider, job.source.split(":", 1)[0]))
            or any(detect_ats(url) == "workday"
                   for url in (job.url, job.application_url or "")))


def canonical_url(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    if detect_ats(url) in {"lever", "ashby"}:
        path = re.sub(r"/(apply|application)$", "", path)
    host = parts.netloc.lower().replace("boards.greenhouse.io", "job-boards.greenhouse.io")
    # Keep unknown query parameters: many ATSs identify the job in the query.
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in
             {"source", "ref", "referrer", "gh_src", "lever-source", "lever-origin"}]
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(sorted(query)), ""))


def requisition(job: Job) -> str | None:
    if job.requisition_id:
        return job.requisition_id
    url = urlsplit(canonical_url(job.url))
    query = dict(parse_qsl(url.query))
    ats = detect_ats(job.url)
    if ats == "greenhouse":
        match = re.search(r"/jobs/(\d+)", url.path)
        return match.group(1) if match else query.get("gh_jid") or query.get("token")
    if ats in {"lever", "ashby"}:
        parts = url.path.strip("/").split("/")
        return parts[-1] if len(parts) >= 2 else None
    if ats == "icims":
        match = re.search(r"/jobs/(\d+)", url.path)
        return match.group(1) if match else None
    if ats == "workday":
        match = re.search(r"_([^/]+)$", url.path)
        return match.group(1) if match else None
    return None


def strong_keys(job: Job) -> set[str]:
    keys = {"legacy:" + job.job_id, "url:" + canonical_url(job.url)}
    if job.application_url:
        keys.add("url:" + canonical_url(job.application_url))
    req = requisition(job)
    if req:
        keys.add(f"req:{normalize_title(job.company)}:{req.lower()}")
    return keys


def possible_key(job: Job) -> str:
    return "|".join((normalize_title(job.company), normalize_title(job.title),
                     normalize_title(job.location_str)))


def prefer_direct(jobs: list[Job]) -> list[Job]:
    """Choose description-rich direct sources before community duplicates."""
    owners: dict[str, Job] = {}
    result = []
    for job in sorted(jobs, key=lambda j: (j.source.startswith("github"), not bool(j.description))):
        keys = strong_keys(job)
        duplicates = [owners[key] for key in keys if key in owners]
        if duplicates:
            # A richer duplicate must not erase a discovery-only provider marker.
            if is_workday_job(job) or any(is_workday_job(old) for old in duplicates):
                for old in duplicates:
                    old.provider = "workday"
            for key in keys:
                owners.setdefault(key, duplicates[0])
            continue
        owners.update({key: job for key in keys})
        result.append(job)
    return result
