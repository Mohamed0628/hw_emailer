"""Greenhouse public board API."""

from __future__ import annotations

import requests

from ..models import Job
from .base import Source, request_json
from .text import plain_text

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
            location = (raw.get("location") or {}).get("name")
            if location:
                locations.append(location)
            for office in raw.get("offices", []) or []:
                name = office.get("name")
                if name and name not in locations:
                    locations.append(name)

            departments = [
                department.get("name")
                for department in (raw.get("departments") or [])
                if isinstance(department, dict) and department.get("name")
            ]
            jobs.append(
                Job(
                    company=self.company,
                    title=str(title),
                    url=str(url),
                    locations=locations,
                    source=self.name,
                    ats="greenhouse",
                    posted_date=(raw.get("updated_at") or "")[:10] or None,
                    description=plain_text(raw.get("content")),
                    department=" | ".join(departments) or None,
                )
            )
        return jobs
