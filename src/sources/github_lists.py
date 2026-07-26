"""Community internship and new-grad job-list sources.

The JSON adapter tolerates schema drift across SimplifyJobs-style repositories.
The README adapter supports common markdown tables where the application link may
appear in any column after company, title, and location.
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
    for text in texts:
        if not text:
            continue
        match = _YEAR_RE.search(str(text))
        if match:
            return int(match.group(1))
    return None


def _map_listing(raw: dict[str, Any], source_name: str) -> Job | None:
    if not isinstance(raw, dict):
        return None
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
        locations=[str(value) for value in locations],
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


# README markdown-table lists.
_APPLY_URL_RE = re.compile(r"\]\((https?://[^\s)]+)\)")
_LINK_TEXT_RE = re.compile(r"\[([^\]]+)\]\(")
_MD_NOISE_RE = re.compile(r"[*`]")


def _clean(cell: str) -> str:
    text = _MD_NOISE_RE.sub("", cell or "").strip()
    match = _LINK_TEXT_RE.search(text)
    return match.group(1).strip() if match else text


def _parse_table_row(
    line: str,
    source_name: str,
    *,
    default_year: int | None = None,
    role_type: str | None = None,
    reject_explicit_other_years: bool = False,
) -> Job | None:
    """Parse a common jobs markdown-table row.

    The first three columns are treated as company, title, and location. The
    application link may appear in any later column because different lists place
    salary, visa, posting, and age columns in different orders.
    """
    stripped = line.strip()
    if not stripped.startswith("|"):
        return None

    cells = [cell.strip() for cell in stripped.strip("|").split("|")]
    if len(cells) < 4:
        return None

    company = _clean(cells[0])
    if not company or company.lower() == "company":
        return None
    if set(cells[0].replace("|", "")) <= set("-: "):
        return None

    title = _clean(cells[1]).rstrip("…").rstrip(".").strip()
    location = _clean(cells[2])

    apply_match = _APPLY_URL_RE.search(" | ".join(cells[3:]))
    url = apply_match.group(1) if apply_match else ""
    if not (company and title and url):
        return None

    explicit_year = _detect_year(title)
    if (
        reject_explicit_other_years
        and default_year is not None
        and explicit_year is not None
        and explicit_year != default_year
    ):
        return None

    return Job(
        company=company,
        title=title,
        url=url,
        locations=[location] if location else [],
        source=source_name,
        ats="github-list",
        year=explicit_year or default_year,
        role_type=role_type,
        active=True,
    )


class GithubReadmeTableSource(Source):
    def __init__(
        self,
        name: str,
        url: str,
        *,
        default_year: int | None = None,
        role_type: str | None = None,
        reject_explicit_other_years: bool = False,
    ):
        self.name = f"githublist:{name}"
        self.url = url
        self.default_year = default_year
        self.role_type = role_type
        self.reject_explicit_other_years = reject_explicit_other_years

    def fetch(self, session) -> list[Job]:
        text = request_text(session, self.url)
        if not text:
            return []

        jobs: list[Job] = []
        seen_urls: set[str] = set()
        for line in text.splitlines():
            job = _parse_table_row(
                line,
                self.name,
                default_year=self.default_year,
                role_type=self.role_type,
                reject_explicit_other_years=self.reject_explicit_other_years,
            )
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
            sources.append(
                GithubReadmeTableSource(
                    entry.get("name") or "table",
                    url,
                    default_year=entry.get("default_year"),
                    role_type=entry.get("role_type"),
                    reject_explicit_other_years=bool(
                        entry.get("reject_explicit_other_years", False)
                    ),
                )
            )
    return sources
