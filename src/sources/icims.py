"""Generic iCIMS job-board source."""

from __future__ import annotations

import re
from html import unescape
from urllib.parse import urljoin

import requests

from ..models import Job
from .base import Source


_JOB_LINK_RE = re.compile(
    r"""href=["'](?P<url>[^"']*/jobs/(?P<id>\d+)/[^"']*)["'][^>]*>
        (?P<title>.*?)
        </a>""",
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)

_TAG_RE = re.compile(r"<[^>]+>")


def _clean_html(value: str) -> str:
    """Convert a small HTML fragment into clean plain text."""
    value = _TAG_RE.sub(" ", value)
    value = unescape(value)
    return " ".join(value.split())


class ICIMSSource(Source):
    """Scrape jobs from a public iCIMS careers page."""

    def __init__(self, company: str, url: str):
        self.company = company
        self.url = url
        self.name = f"icims:{company}"

    def fetch(self, session: requests.Session) -> list[Job]:
        try:
            response = session.get(self.url, timeout=30)
            response.raise_for_status()
        except requests.RequestException:
            return []

        jobs: list[Job] = []
        seen_urls: set[str] = set()

        for match in _JOB_LINK_RE.finditer(response.text):
            raw_url = match.group("url")
            title = _clean_html(match.group("title"))

            if not title:
                continue

            url = urljoin(response.url, raw_url)

            if url in seen_urls:
                continue

            seen_urls.add(url)

            jobs.append(
                Job(
                    company=self.company,
                    title=title,
                    url=url,
                    locations=[],
                    source=self.name,
                    ats="icims",
                    posted_date=None,
                )
            )
        return jobs

