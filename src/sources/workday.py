"""Workday CXS public jobs endpoint.

Configured Minnesota medtech employers can use several targeted search terms so
full-time Engineer I, associate, rotational, and description-qualified roles
reach the local filter. Individual job details are fetched once per unique
posting to obtain requirements and experience language.
"""

from __future__ import annotations

import requests

from ..models import Job
from .base import Source, request_json
from .text import plain_text

PAGE = 20
MAX_PAGES = 25


class WorkdaySource(Source):
    def __init__(
        self,
        company: str,
        tenant: str,
        wd_num,
        site: str,
        search_text: str = "intern",
        search_texts: list[str] | None = None,
        fetch_details: bool = False,
    ):
        self.company = company
        self.tenant = tenant
        self.wd_num = wd_num
        self.site = site
        terms = search_texts or [search_text]
        self.search_texts = list(
            dict.fromkeys(str(term).strip() for term in terms if str(term).strip())
        )
        self.fetch_details = fetch_details
        self.name = f"workday:{company}"
        self.base = f"https://{tenant}.wd{wd_num}.myworkdayjobs.com"
        self.api = f"{self.base}/wday/cxs/{tenant}/{site}/jobs"

    def _job_url(self, external_path: str) -> str:
        return f"{self.base}/en-US/{self.site}{external_path}"

    def _detail_url(self, external_path: str) -> str:
        return f"{self.base}/wday/cxs/{self.tenant}/{self.site}{external_path}"

    def _fetch_detail(
        self,
        session: requests.Session,
        external_path: str,
    ) -> dict:
        if not self.fetch_details:
            return {}
        data = request_json(session, "GET", self._detail_url(external_path))
        if not isinstance(data, dict):
            return {}
        info = data.get("jobPostingInfo")
        return info if isinstance(info, dict) else {}

    def fetch(self, session: requests.Session) -> list[Job]:
        postings_by_path: dict[str, dict] = {}

        for search_text in self.search_texts:
            offset = 0
            for _ in range(MAX_PAGES):
                body = {
                    "appliedFacets": {},
                    "limit": PAGE,
                    "offset": offset,
                    "searchText": search_text,
                }
                data = request_json(
                    session,
                    "POST",
                    self.api,
                    json_body=body,
                )
                if not data or not isinstance(data, dict):
                    break

                postings = data.get("jobPostings") or []
                if not postings:
                    break

                for raw in postings:
                    title = raw.get("title")
                    external_path = raw.get("externalPath")
                    if title and external_path:
                        postings_by_path.setdefault(str(external_path), raw)

                offset += PAGE
                if offset >= int(data.get("total", 0)):
                    break

        jobs: list[Job] = []
        for external_path, raw in postings_by_path.items():
            title = raw.get("title")
            if not title:
                continue

            detail = self._fetch_detail(session, external_path)
            location = (
                detail.get("location")
                or detail.get("locationsText")
                or raw.get("locationsText")
            )
            additional_locations = detail.get("additionalLocations") or []
            locations: list[str] = []
            if location:
                locations.append(str(location))
            if isinstance(additional_locations, list):
                for item in additional_locations:
                    value = item.get("location") if isinstance(item, dict) else item
                    if value and str(value) not in locations:
                        locations.append(str(value))

            jobs.append(
                Job(
                    company=self.company,
                    title=str(detail.get("title") or title),
                    url=self._job_url(external_path),
                    locations=locations,
                    source=self.name,
                    ats="workday",
                    posted_date=None,
                    description=plain_text(
                        detail.get("jobDescription")
                        or detail.get("description")
                    ),
                    department=detail.get("jobFamilyGroup"),
                    team=detail.get("jobFamily"),
                    employment_type=detail.get("timeType"),
                )
            )
        return jobs
