"""Lever public postings API.

    GET https://api.lever.co/v0/postings/{token}?mode=json
    -> [{"text": title, "hostedUrl", "categories": {"location", "team", "commitment"},
         "country", "createdAt"(ms)}]
"""

from __future__ import annotations

from datetime import datetime, timezone

import requests

from ..models import Job
from .base import Source, request_json

API = "https://api.lever.co/v0/postings/{token}"


def _ms_to_iso(ms) -> str | None:
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).date().isoformat()
    except (ValueError, OSError, TypeError):
        return None


class LeverSource(Source):
    def __init__(self, company: str, token: str):
        self.company = company
        self.token = token
        self.name = f"lever:{company}"

    def fetch(self, session: requests.Session) -> list[Job]:
        data = request_json(
            session, "GET", API.format(token=self.token), params={"mode": "json"}
        )
        if not isinstance(data, list):
            return []
        jobs: list[Job] = []
        for raw in data:
            title = raw.get("text")
            url = raw.get("hostedUrl") or raw.get("applyUrl")
            if not (title and url):
                continue
            cats = raw.get("categories") or {}
            locations: list[str] = []
            if cats.get("location"):
                locations.append(cats["location"])
            if raw.get("country") and raw["country"] not in locations:
                locations.append(raw["country"])
            jobs.append(
                Job(
                    company=self.company,
                    title=str(title),
                    url=str(url),
                    locations=locations,
                    source=self.name,
                    ats="lever",
                    posted_date=_ms_to_iso(raw.get("createdAt")),
                )
            )
        return jobs
