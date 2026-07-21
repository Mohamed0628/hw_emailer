"""Greenhouse public board API.

    GET https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true
    -> {"jobs": [{"title", "absolute_url", "location": {"name"}, "offices": [...],
                  "updated_at"}]}
"""

from __future__ import annotations

import requests

from ..models import Job
from .base import Source, request_json

API = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


class GreenhouseSource(Source):
    def __init__(self, company: str, token: str):
        self.company = company
        self.token = token
        self.name = f"greenhouse:{company}"

    def fetch(self, session: requests.Session) -> list[Job]:
        data = request_json(
            session, "GET", API.format(token=self.token), params={"content": "true"}
        )
        if not data or not isinstance(data, dict):
            return []
        jobs: list[Job] = []
        for raw in data.get("jobs", []) or []:
            title = raw.get("title")
            url = raw.get("absolute_url")
            if not (title and url):
                continue
            locations: list[str] = []
            loc = (raw.get("location") or {}).get("name")
            if loc:
                locations.append(loc)
            for office in raw.get("offices", []) or []:
                nm = office.get("name")
                if nm and nm not in locations:
                    locations.append(nm)
            jobs.append(
                Job(
                    company=self.company,
                    title=str(title),
                    url=str(url),
                    locations=locations,
                    source=self.name,
                    ats="greenhouse",
                    posted_date=(raw.get("updated_at") or "")[:10] or None,
                )
            )
        return jobs
