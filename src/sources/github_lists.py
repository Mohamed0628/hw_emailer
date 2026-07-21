"""Community internship aggregators that publish a `listings.json`.

Tolerant of schema drift across forks — every field access is defensive.
The canonical schema (SimplifyJobs) looks like:

    {
      "company_name": "Acme",
      "title": "Software Engineer Intern",
      "locations": ["New York, NY"],
      "url": "https://...",
      "active": true,
      "is_visible": true,
      "season": "Summer",
      "terms": ["Summer 2026"],
      "sponsorship": "Does Not Offer Sponsorship",
      "date_posted": 1700000000
    }
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import requests

from .. import config
from ..models import Job
from .base import Source, request_json, request_text

log = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _to_iso(ts: Any) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
    except (ValueError, OSError, TypeError):
        return None


def _detect_year(*texts: Any) -> int | None:
    for t in texts:
        if not t:
            continue
        m = _YEAR_RE.search(str(t))
        if m:
            return int(m.group(1))
    return None


def _map_listing(raw: dict[str, Any], source_name: str) -> Job | None:
    if not isinstance(raw, dict):
        return None
    # Respect visibility/active flags when present.
    if raw.get("is_visible") is False:
        return None

    company = raw.get("company_name") or raw.get("company") or ""
    title = raw.get("title") or ""
    url = raw.get("url") or raw.get("company_url") or ""
    if not (company and title and url):
        return None

    locations = raw.get("locations") or []
    if isinstance(locations, str):
        locations = [locations]

    season = raw.get("season")
    terms = raw.get("terms") or []
    year = _detect_year(*(terms if isinstance(terms, list) else [terms]), title)

    return Job(
        company=str(company),
        title=str(title),
        url=str(url),
        locations=[str(x) for x in locations],
        source=source_name,
        ats="github-list",
        season=str(season).lower() if season else None,
        year=year,
        posted_date=_to_iso(raw.get("date_posted")),
        sponsorship=raw.get("sponsorship"),
        active=bool(raw.get("active", True)),
    )


class GithubListSource(Source):
    def __init__(self, name: str, url: str):
        self.name = f"githublist:{name}"
        self.url = url

    def fetch(self, session: requests.Session) -> list[Job]:
        data = request_json(session, "GET", self.url)
        if data is None:
            return []
        # listings.json is usually a top-level array; some forks wrap it.
        if isinstance(data, dict):
            data = data.get("listings") or data.get("data") or []
        if not isinstance(data, list):
            log.warning("%s: unexpected JSON shape", self.name)
            return []
        jobs: list[Job] = []
        for raw in data:
            job = _map_listing(raw, self.name)
            if job and job.active:
                jobs.append(job)
        return jobs


# --- README markdown-table lists (e.g. zapplyjobs) -------------------------
# Rows look like: | **Company** | Role… | Location | 14m | visa | [Apply](url) |
# Titles are often truncated with "…"; the apply URL and company come through
# fully, and dedup keys on the URL, so truncation is harmless.

_APPLY_URL_RE = re.compile(r"\]\((https?://[^\s)]+)\)")
_LINK_TEXT_RE = re.compile(r"\[([^\]]+)\]\(")
_MD_NOISE_RE = re.compile(r"[*`]")


def _clean(cell: str) -> str:
    text = _MD_NOISE_RE.sub("", cell or "").strip()
    m = _LINK_TEXT_RE.search(text)  # unwrap [Name](url) -> Name
    return (m.group(1).strip() if m else text)


def _parse_table_row(line: str, source_name: str) -> Job | None:
    s = line.strip()
    if not s.startswith("|"):
        return None
    cells = [c.strip() for c in s.strip("|").split("|")]
    if len(cells) < 6:
        return None
    company = _clean(cells[0])
    if not company or company.lower() == "company":
        return None
    if set(cells[0].replace("|", "")) <= set("-: "):  # separator row
        return None

    title = _clean(cells[1]).rstrip("…").rstrip(".").strip()
    location = _clean(cells[2])
    m = _APPLY_URL_RE.search(cells[-1])
    url = m.group(1) if m else ""
    if not (company and title and url):
        return None

    return Job(
        company=company,
        title=title,
        url=url,
        locations=[location] if location else [],
        source=source_name,
        ats="github-list",
        year=_detect_year(title),
        active=True,
    )


class GithubReadmeTableSource(Source):
    def __init__(self, name: str, url: str):
        self.name = f"githublist:{name}"
        self.url = url

    def fetch(self, session) -> list[Job]:
        text = request_text(session, self.url)
        if not text:
            return []
        jobs: list[Job] = []
        seen_urls: set[str] = set()
        for line in text.splitlines():
            job = _parse_table_row(line, self.name)
            if job and job.url not in seen_urls:
                seen_urls.add(job.url)
                jobs.append(job)
        return jobs


def build_sources() -> list[Source]:
    cfg = config.github_lists()
    if not cfg.get("enabled", True):
        return []
    sources: list[Source] = []
    for entry in cfg.get("lists", []) or []:
        if entry.get("enabled", True) is False:
            continue
        url = entry.get("url")
        if url:
            sources.append(GithubListSource(entry.get("name") or "list", url))
    for entry in cfg.get("readme_tables", []) or []:
        if entry.get("enabled", True) is False:
            continue
        url = entry.get("url")
        if url:
            sources.append(GithubReadmeTableSource(entry.get("name") or "table", url))
    return sources
