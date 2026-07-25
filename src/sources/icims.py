"""Generic iCIMS job-board source."""

from __future__ import annotations

import re
from urllib.parse import urljoin

import requests

from ..models import Job
from .base import Source
from .text import plain_text

_JOB_LINK_RE = re.compile(
    r"""href=["'](?P<url>[^"']*/jobs/(?P<id>\d+)/[^"']*)["'][^>]*>
        (?P<title>.*?)
        </a>""",
    re.IGNORECASE | re.DOTALL | re.VERBOSE,
)

_LOCATION_RE = re.compile(
    r"(?:Location|Job Locations?)\s*</?[^>]*>\s*(?P<location>[^<]{2,120})",
    re.IGNORECASE,
)


class ICIMSSource(Source):
    """Scrape jobs from a public iCIMS careers page."""

    def __init__(self, company: str, url: str, fetch_details: bool = False):
        self.company = company
        self.url = url
        self.fetch_details = fetch_details
        self.name = f"icims:{company}"

    def _detail(
        self,
        session: requests.Session,
        url: str,
    ) -> tuple[str, list[str]]:
        if not self.fetch_details:
            return "", []
        try:
            response = session.get(url, timeout=30)
            response.raise_for_status()
        except requests.RequestException:
            return "", []

        locations: list[str] = []
        match = _LOCATION_RE.search(response.text)
        if match:
            location = plain_text(match.group("location"))
            if location:
                locations.append(location)

        return plain_text(response.text), locations

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
            title = plain_text(match.group("title"))
            if not title:
                continue

            url = urljoin(response.url, raw_url)
            if url in seen_urls:
                continue
            seen_urls.add(url)

            description, locations = self._detail(session, url)
            jobs.append(
                Job(
                    company=self.company,
                    title=title,
                    url=url,
                    locations=locations,
                    source=self.name,
                    ats="icims",
                    posted_date=None,
                    description=description or None,
                )
            )
        return jobs
