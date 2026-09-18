"""Workday CXS public jobs endpoint.

Configured Minnesota medtech employers can use several targeted search terms so
full-time Engineer I, associate, rotational, and description-qualified roles
reach the local filter. Job details are fetched once per unique plausible title
to obtain requirements and degree-specific experience language.
"""

from __future__ import annotations

import logging
import time

import requests

from ..models import Job
from ..smart_filters import potential_technical_title
from .base import Source
from .text import plain_text

PAGE = 20
MAX_PAGES = 10
REQUEST_TIMEOUT = (3, 8)  # connect/read seconds; independent of global retry settings
MAX_ATTEMPTS = 2
log = logging.getLogger(__name__)


class WorkdayRequestError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


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
            dict.fromkeys(
                str(term).strip()
                for term in terms
                if str(term).strip()
            )
        )
        self.fetch_details = fetch_details
        self.name = f"workday:{company}"
        self.base = f"https://{tenant}.wd{wd_num}.myworkdayjobs.com"
        self.api = f"{self.base}/wday/cxs/{tenant}/{site}/jobs"

    def _job_url(self, external_path: str) -> str:
        return f"{self.base}/en-US/{self.site}{external_path}"

    def _detail_url(self, external_path: str) -> str:
        return f"{self.base}/wday/cxs/{self.tenant}/{self.site}{external_path}"

    def _request_json(self, session, method, url, *, json_body=None):
        """One retry for transient failures only; never repeat deterministic 4xx."""
        for attempt in range(MAX_ATTEMPTS):
            status = None
            try:
                response = session.request(method, url, json=json_body, timeout=REQUEST_TIMEOUT)
                status = response.status_code
                if status >= 400:
                    raise WorkdayRequestError(f"HTTP {status}", status)
                data = response.json()
                if not isinstance(data, dict):
                    raise WorkdayRequestError("expected JSON object")
                return data
            except (requests.Timeout, requests.ConnectionError) as exc:
                transient = True
                error = WorkdayRequestError(type(exc).__name__)
            except (ValueError, requests.RequestException, WorkdayRequestError) as exc:
                transient = status in {408, 429} or (status is not None and 500 <= status < 600)
                error = WorkdayRequestError(str(exc), status)
            if not transient or attempt + 1 == MAX_ATTEMPTS:
                log.warning("%s %s failed: %s (%s; attempts=%d)",
                            self.name, method, url, error, attempt + 1)
                raise error
            time.sleep(0.5)

    def _fetch_detail(
        self,
        session: requests.Session,
        external_path: str,
    ) -> dict:
        if not self.fetch_details:
            return {}
        data = self._request_json(session, "GET", self._detail_url(external_path))
        if not isinstance(data, dict):
            return {}
        info = data.get("jobPostingInfo")
        return info if isinstance(info, dict) else {}

    def fetch(self, session: requests.Session) -> list[Job]:
        postings_by_path: dict[str, dict] = {}
        search_failed = False

        for search_text in self.search_texts:
            offset = 0
            for _ in range(MAX_PAGES):
                body = {
                    "appliedFacets": {},
                    "limit": PAGE,
                    "offset": offset,
                    "searchText": search_text,
                }
                try:
                    data = self._request_json(session, "POST", self.api, json_body=body)
                    if not isinstance(data.get("jobPostings"), list):
                        raise WorkdayRequestError("missing/invalid jobPostings list")
                except WorkdayRequestError as exc:
                    log.warning("%s stopping searches for this endpoint (%s); preserving %d postings",
                                self.name, exc, len(postings_by_path))
                    search_failed = True
                    break

                postings = data.get("jobPostings") or []
                if not postings:
                    break

                for raw in postings:
                    if not isinstance(raw, dict):
                        log.warning("%s skipping malformed posting", self.name)
                        continue
                    title = raw.get("title")
                    external_path = raw.get("externalPath")
                    if not (title and external_path):
                        continue
                    if self.fetch_details and not potential_technical_title(
                        str(title)
                    ):
                        continue
                    postings_by_path.setdefault(str(external_path), raw)

                offset += PAGE
                try:
                    total = int(data.get("total", 0))
                except (TypeError, ValueError):
                    log.warning("%s invalid pagination total; preserving collected postings", self.name)
                    search_failed = True
                    break
                if offset >= total:
                    break
            if search_failed:
                break  # Do not hammer the same failed endpoint for every search term.

        jobs: list[Job] = []
        detail_failures = 0
        stop_details = False
        for external_path, raw in postings_by_path.items():
            title = raw.get("title")
            if not title:
                continue

            detail = {}
            if not stop_details:
                try:
                    detail = self._fetch_detail(session, external_path)
                    detail_failures = 0
                except WorkdayRequestError as exc:
                    # A missing individual posting must not prevent another valid detail.
                    if exc.status not in {404, 422}:
                        detail_failures += 1
                    else:
                        detail_failures = 0
                    if exc.status in {401, 403} or detail_failures >= 3:
                        stop_details = True
                        log.warning("%s stopping failing detail requests; retaining listing metadata for remaining jobs",
                                    self.name)
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
                    value = (
                        item.get("location")
                        if isinstance(item, dict)
                        else item
                    )
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
                    requisition_id=str(detail.get("jobReqId") or "") or None,
                    posted_date=None,
                    description=plain_text(
                        detail.get("jobDescription")
                        or detail.get("description")
                        or raw.get("jobDescription")
                        or raw.get("description")
                    ),
                    department=detail.get("jobFamilyGroup"),
                    team=detail.get("jobFamily"),
                    employment_type=detail.get("timeType"),
                )
            )
        return jobs
