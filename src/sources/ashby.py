"""Ashby public job-board API."""

from __future__ import annotations

import requests

from ..models import Job
from .base import Source, request_json
from .text import plain_text

API = "https://api.ashbyhq.com/posting-api/job-board/{token}"


class AshbySource(Source):
    def __init__(self, company: str, token: str):
        self.company = company
        self.token = token
        self.name = f"ashby:{company}"

    def fetch(self, session: requests.Session) -> list[Job]:
        data = request_json(
            session,
            "GET",
            API.format(token=self.token),
            params={"includeCompensation": "true"},
        )
        if not data or not isinstance(data, dict):
            return []

        jobs: list[Job] = []
        for raw in data.get("jobs", []) or []:
            if raw.get("isListed") is False:
                continue
            title = raw.get("title")
            url = raw.get("jobUrl") or raw.get("applyUrl")
            if not (title and url):
                continue

            locations: list[str] = []
            if raw.get("location"):
                locations.append(raw["location"])
            for secondary in raw.get("secondaryLocations", []) or []:
                location = secondary.get("location") if isinstance(secondary, dict) else secondary
                if location and location not in locations:
                    locations.append(location)
            if raw.get("isRemote") and not any("remote" in location.lower() for location in locations):
                locations.append("Remote")

            jobs.append(
                Job(
                    company=self.company,
                    title=str(title),
                    url=str(url),
                    locations=locations,
                    source=self.name,
                    ats="ashby",
                    posted_date=(raw.get("publishedAt") or "")[:10] or None,
                    description=plain_text(
                        raw.get("descriptionPlain")
                        or raw.get("descriptionHtml")
                        or raw.get("description")
                    ),
                    department=raw.get("department"),
                    team=raw.get("team"),
                    employment_type=raw.get("employmentType"),
                )
            )
        return jobs
