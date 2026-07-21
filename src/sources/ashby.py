"""Ashby public job-board API.

    GET https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true
    -> {"jobs": [{"title", "location", "secondaryLocations": [{"location"}],
                  "isRemote", "isListed", "jobUrl", "applyUrl", "publishedAt",
                  "employmentType"}]}
"""

from __future__ import annotations

import requests

from ..models import Job
from .base import Source, request_json

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
            for sec in raw.get("secondaryLocations", []) or []:
                loc = sec.get("location") if isinstance(sec, dict) else sec
                if loc and loc not in locations:
                    locations.append(loc)
            if raw.get("isRemote") and not any("remote" in l.lower() for l in locations):
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
                )
            )
        return jobs
