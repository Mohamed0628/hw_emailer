"""Workday CXS public jobs endpoint (used by many banks / big tech / consulting).

    POST https://{tenant}.wd{n}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs
    body: {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}
    -> {"total", "jobPostings": [{"title", "externalPath", "locationsText",
                                  "postedOn", "bulletFields"}]}

Job URL = https://{tenant}.wd{n}.myworkdayjobs.com/en-US/{site}{externalPath}
"""

from __future__ import annotations

import requests

from ..models import Job
from .base import Source, request_json

PAGE = 20
MAX_PAGES = 25  # safety cap (=500 postings/company)


class WorkdaySource(Source):
    def __init__(self, company: str, tenant: str, wd_num, site: str, search_text: str = "intern"):
        self.company = company
        self.tenant = tenant
        self.wd_num = wd_num
        self.site = site
        # Narrow the server-side search so we don't page through thousands of
        # unrelated roles; filtering still happens locally.
        self.search_text = search_text
        self.name = f"workday:{company}"
        self.base = f"https://{tenant}.wd{wd_num}.myworkdayjobs.com"
        self.api = f"{self.base}/wday/cxs/{tenant}/{site}/jobs"

    def _job_url(self, external_path: str) -> str:
        return f"{self.base}/en-US/{self.site}{external_path}"

    def fetch(self, session: requests.Session) -> list[Job]:
        jobs: list[Job] = []
        offset = 0
        for _ in range(MAX_PAGES):
            body = {
                "appliedFacets": {},
                "limit": PAGE,
                "offset": offset,
                "searchText": self.search_text,
            }
            data = request_json(
                session, "POST", self.api, json_body=body
            )
            if not data or not isinstance(data, dict):
                break
            postings = data.get("jobPostings") or []
            if not postings:
                break
            for raw in postings:
                title = raw.get("title")
                ext = raw.get("externalPath")
                if not (title and ext):
                    continue
                loc = raw.get("locationsText")
                jobs.append(
                    Job(
                        company=self.company,
                        title=str(title),
                        url=self._job_url(ext),
                        locations=[loc] if loc else [],
                        source=self.name,
                        ats="workday",
                        posted_date=None,  # Workday gives relative text ("Posted 3 days ago")
                    )
                )
            offset += PAGE
            if offset >= int(data.get("total", 0)):
                break
        return jobs
