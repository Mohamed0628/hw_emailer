"""Direct career-board adapters for targeted Minnesota engineering employers.

These adapters cover public job boards that are not handled by Greenhouse, Lever,
Ashby, Workday, or iCIMS. Each source returns the shared Job model so the normal
smart filters, deduplication, and notifications continue to work unchanged.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, Optional
from urllib.parse import urlencode, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag

from ..models import Job
from .base import Source, request_json, request_text
from .text import plain_text

log = logging.getLogger(__name__)

_LOCATION_RE = re.compile(
    r"\b([A-Z][A-Za-z.'’ -]+(?:\s+[A-Z][A-Za-z.'’ -]+)*,\s*[A-Z]{2})\b"
)
_GENERIC_LINK_TEXT = {
    "apply",
    "apply now",
    "learn more",
    "read more",
    "view",
    "view job",
    "view details",
    "details",
}


def _date(value: object) -> Optional[str]:
    text = str(value or "").strip()
    return text[:10] or None


def _dedupe(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        value = str(value or "").strip()
        if value and value not in out:
            out.append(value)
    return out


def _location_from_text(value: str) -> Optional[str]:
    match = _LOCATION_RE.search(" ".join((value or "").split()))
    return match.group(1).strip() if match else None


def _address_location(address: object) -> Optional[str]:
    if not isinstance(address, dict):
        return None
    city = str(address.get("addressLocality") or address.get("city") or "").strip()
    state_value = address.get("addressRegion") or address.get("state") or ""
    if isinstance(state_value, dict):
        state_value = state_value.get("codeValue") or state_value.get("shortName") or ""
    state = str(state_value).strip()
    country_value = address.get("addressCountry") or address.get("country") or ""
    if isinstance(country_value, dict):
        country_value = country_value.get("name") or country_value.get("code") or ""
    country = str(country_value).strip()
    if city and state:
        return f"{city}, {state}"
    if city and country:
        return f"{city}, {country}"
    return city or state or country or None


def _json_ld_nodes(soup: BeautifulSoup) -> Iterable[dict[str, Any]]:
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        stack = payload if isinstance(payload, list) else [payload]
        for item in stack:
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                for node in graph:
                    if isinstance(node, dict):
                        yield node
            yield item


def _job_json_ld(soup: BeautifulSoup) -> dict[str, Any]:
    for node in _json_ld_nodes(soup):
        kind = node.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]
        if any(str(value).lower() == "jobposting" for value in kinds):
            return node
    return {}


def _json_ld_locations(node: dict[str, Any]) -> list[str]:
    raw_locations = node.get("jobLocation") or []
    if isinstance(raw_locations, dict):
        raw_locations = [raw_locations]
    locations: list[str] = []
    for raw in raw_locations if isinstance(raw_locations, list) else []:
        if not isinstance(raw, dict):
            continue
        location = _address_location(raw.get("address") or raw)
        if location:
            locations.append(location)
    applicant = node.get("applicantLocationRequirements")
    if isinstance(applicant, dict):
        name = applicant.get("name")
        if name:
            locations.append(str(name))
    return _dedupe(locations)


def _nearest_heading(anchor: Tag) -> Optional[str]:
    text = anchor.get_text(" ", strip=True)
    if text and text.lower() not in _GENERIC_LINK_TEXT and len(text) >= 4:
        return text
    current: Optional[Tag] = anchor
    for _ in range(6):
        current = current.parent if isinstance(current, Tag) else None
        if current is None:
            break
        heading = current.find(["h1", "h2", "h3", "h4", "h5", "strong"])
        if heading:
            candidate = heading.get_text(" ", strip=True)
            if candidate and candidate.lower() not in _GENERIC_LINK_TEXT:
                return candidate
    return None


def _detail_from_html(
    html: str,
    *,
    fallback_title: str = "",
    fallback_location: str = "",
) -> dict[str, Any]:
    soup = BeautifulSoup(html or "", "lxml")
    node = _job_json_ld(soup)

    title = str(node.get("title") or "").strip()
    if not title:
        heading = soup.find("h1") or soup.find("h2")
        title = heading.get_text(" ", strip=True) if heading else fallback_title

    description = plain_text(node.get("description"))
    if not description:
        body = (
            soup.select_one("[class*='job-description']")
            or soup.select_one("[id*='job-description']")
            or soup.find("article")
            or soup.find("main")
        )
        description = plain_text(body.get_text(" ", strip=True) if body else "")

    locations = _json_ld_locations(node)
    if not locations:
        text_location = _location_from_text(soup.get_text(" ", strip=True))
        locations = _dedupe([text_location or fallback_location])

    employment = node.get("employmentType")
    if isinstance(employment, list):
        employment = ", ".join(str(value) for value in employment)

    return {
        "title": title or fallback_title,
        "description": description,
        "locations": locations,
        "posted_date": _date(node.get("datePosted")),
        "employment_type": str(employment).strip() if employment else None,
    }


class JazzHRSource(Source):
    """Scrape a public JazzHR applytojob.com board and its detail pages."""

    def __init__(self, company: str, board_url: str, default_location: str = ""):
        self.company = company
        self.board_url = board_url.rstrip("/")
        self.default_location = default_location
        self.name = f"jazzhr:{company}"

    def fetch(self, session: requests.Session) -> list[Job]:
        html = request_text(session, self.board_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "lxml")
        board = urlparse(self.board_url)
        base_path = board.path.rstrip("/")
        links: dict[str, tuple[str, str]] = {}

        for anchor in soup.find_all("a", href=True):
            url = urljoin(self.board_url + "/", anchor["href"])
            parsed = urlparse(url)
            if parsed.netloc != board.netloc:
                continue
            path = parsed.path.rstrip("/")
            if not path.startswith(base_path + "/") or "/apply/" not in path + "/":
                continue
            title = _nearest_heading(anchor) or ""
            container_text = anchor.parent.get_text(" ", strip=True) if anchor.parent else ""
            location = _location_from_text(container_text) or self.default_location
            if title:
                links[url] = (title, location)

        jobs: list[Job] = []
        for url, (fallback_title, fallback_location) in links.items():
            detail_html = request_text(session, url) or ""
            detail = _detail_from_html(
                detail_html,
                fallback_title=fallback_title,
                fallback_location=fallback_location,
            )
            jobs.append(
                Job(
                    company=self.company,
                    title=detail["title"],
                    url=url,
                    locations=detail["locations"],
                    source=self.name,
                    ats="jazzhr",
                    posted_date=detail["posted_date"],
                    description=detail["description"],
                    employment_type=detail["employment_type"],
                )
            )
        return jobs


class PaylocitySource(Source):
    """Fetch jobs from Paylocity's public Recruiting Job Feed V2."""

    API = "https://recruiting.paylocity.com/recruiting/v2/api/feed/jobs/{guid}"

    def __init__(self, company: str, guid: str):
        self.company = company
        self.guid = guid
        self.name = f"paylocity:{company}"

    @staticmethod
    def _location(raw: object) -> list[str]:
        if isinstance(raw, str):
            return [raw] if raw.strip() else []
        if not isinstance(raw, dict):
            return []
        display = (
            raw.get("displayName")
            or raw.get("locationName")
            or raw.get("locationString")
        )
        if display:
            return [str(display)]
        location = _address_location(raw)
        return [location] if location else []

    def fetch(self, session: requests.Session) -> list[Job]:
        data = request_json(session, "GET", self.API.format(guid=self.guid))
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = data.get("jobs") or data.get("jobListings") or data.get("items") or []
        else:
            return []

        jobs: list[Job] = []
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            title = raw.get("jobTitle") or raw.get("title")
            url = raw.get("applyUrl") or raw.get("displayUrl") or raw.get("url")
            if not title or not url:
                continue
            types = raw.get("jobTypesArray") or raw.get("jobTypes") or []
            if isinstance(types, list):
                employment_type = ", ".join(
                    str(item.get("name") if isinstance(item, dict) else item)
                    for item in types
                    if item
                ) or None
            else:
                employment_type = str(types) if types else None
            description = plain_text(
                " ".join(
                    str(value or "")
                    for value in (raw.get("description"), raw.get("requirements"))
                )
            )
            jobs.append(
                Job(
                    company=self.company,
                    title=str(title),
                    url=str(url),
                    locations=self._location(raw.get("jobLocation")),
                    source=self.name,
                    ats="paylocity",
                    posted_date=_date(raw.get("publishedDate")),
                    description=description,
                    department=raw.get("hiringDepartment"),
                    employment_type=employment_type,
                )
            )
        return jobs


class UKGProSource(Source):
    """Fetch jobs from the public UKG Pro / UltiPro Recruiting board API."""

    PAGE_SIZE = 50
    _DETAIL_ANCHOR = re.compile(r"CandidateOpportunityDetail\(")

    def __init__(self, company: str, host: str, code: str, board: str):
        self.company = company
        self.host = host
        self.code = code
        self.board = board
        self.base = f"https://{host}/{code}/JobBoard/{board}"
        self.name = f"ukg:{company}"

    @classmethod
    def _search_body(cls, skip: int) -> dict[str, Any]:
        return {
            "opportunitySearch": {
                "Top": cls.PAGE_SIZE,
                "Skip": skip,
                "QueryString": "",
                "OrderBy": [
                    {
                        "Value": "postedDateDesc",
                        "PropertyName": "PostedDate",
                        "Ascending": False,
                    }
                ],
                "Filters": [],
            },
            "matchCriteria": {
                "PreferredJobs": [],
                "Educations": [],
                "LicenseAndCertifications": [],
                "Skills": [],
                "hasNoLicenses": False,
                "SkippedSkills": [],
            },
        }

    @classmethod
    def _extract_detail(cls, html: str) -> dict[str, Any]:
        match = cls._DETAIL_ANCHOR.search(html or "")
        if not match:
            return {}
        start = match.end()
        while start < len(html) and html[start].isspace():
            start += 1
        try:
            payload, _ = json.JSONDecoder().raw_decode(html, start)
            return payload if isinstance(payload, dict) else {}
        except ValueError:
            return {}

    @staticmethod
    def _locations(raw_locations: object) -> list[str]:
        locations: list[str] = []
        if not isinstance(raw_locations, list):
            return locations
        for raw in raw_locations:
            if not isinstance(raw, dict):
                continue
            address = raw.get("Address") or {}
            city = str(address.get("City") or "").strip()
            state_raw = address.get("State") or {}
            state = str(
                state_raw.get("Code") or state_raw.get("Name") or ""
            ).strip() if isinstance(state_raw, dict) else str(state_raw).strip()
            country_raw = address.get("Country") or {}
            country = str(
                country_raw.get("Name") or country_raw.get("Code") or ""
            ).strip() if isinstance(country_raw, dict) else str(country_raw).strip()
            display = (
                f"{city}, {state}" if city and state
                else f"{city}, {country}" if city and country
                else city
                or str(raw.get("LocalizedDescription") or "").strip()
            )
            if display:
                locations.append(display)
        return _dedupe(locations)

    def fetch(self, session: requests.Session) -> list[Job]:
        opportunities: dict[str, dict[str, Any]] = {}
        skip = 0
        for _ in range(20):
            data = request_json(
                session,
                "POST",
                f"{self.base}/JobBoardView/LoadSearchResults",
                json_body=self._search_body(skip),
            )
            if not isinstance(data, dict):
                break
            rows = data.get("opportunities") or []
            if not rows:
                break
            for raw in rows:
                if isinstance(raw, dict) and raw.get("Id"):
                    opportunities[str(raw["Id"])] = raw
            skip += self.PAGE_SIZE
            if skip >= int(data.get("totalCount") or 0):
                break

        jobs: list[Job] = []
        for opportunity_id, raw in opportunities.items():
            url = f"{self.base}/OpportunityDetail?opportunityId={opportunity_id}"
            detail = self._extract_detail(request_text(session, url) or "")
            source = detail or raw
            title = source.get("Title") or raw.get("Title")
            if not title:
                continue
            full_time = source.get("FullTime")
            employment_type = (
                "Full-time" if full_time is True
                else "Part-time" if full_time is False
                else None
            )
            jobs.append(
                Job(
                    company=self.company,
                    title=plain_text(title),
                    url=url,
                    locations=self._locations(
                        source.get("Locations") or raw.get("Locations") or []
                    ),
                    source=self.name,
                    ats="ukg",
                    posted_date=_date(
                        source.get("PostedDate") or raw.get("PostedDate")
                    ),
                    description=plain_text(
                        source.get("Description") or raw.get("BriefDescription")
                    ),
                    department=(
                        source.get("JobCategoryName") or raw.get("JobCategoryName")
                    ),
                    employment_type=employment_type,
                )
            )
        return jobs


class ADPSource(Source):
    """Fetch jobs from ADP Workforce Now's public career-center API."""

    API = (
        "https://workforcenow.adp.com/mascsr/default/careercenter/public/events/"
        "staffing/v1/job-requisitions"
    )
    PORTAL = (
        "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/"
        "recruitment.html"
    )

    def __init__(
        self,
        company: str,
        cid: str,
        cc_id: str = "19000101_000001",
        lang: str = "en_US",
    ):
        self.company = company
        self.cid = cid
        self.cc_id = cc_id
        self.lang = lang
        self.name = f"adp:{company}"

    def _params(self, *, top: int | None = None, skip: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {
            "cid": self.cid,
            "ccId": self.cc_id,
            "lang": self.lang,
        }
        if top is not None:
            params["$top"] = top
        if skip is not None:
            params["$skip"] = skip
        return params

    @staticmethod
    def _locations(raw: dict[str, Any]) -> list[str]:
        locations: list[str] = []
        for item in raw.get("requisitionLocations") or []:
            if not isinstance(item, dict):
                continue
            name = (item.get("nameCode") or {}).get("shortName")
            if name:
                locations.append(str(name))
                continue
            location = _address_location(item.get("address") or {})
            if location:
                locations.append(location)
        return _dedupe(locations)

    @staticmethod
    def _external_id(raw: dict[str, Any]) -> str:
        fields = (raw.get("customFieldGroup") or {}).get("stringFields") or []
        for field in fields:
            if not isinstance(field, dict):
                continue
            code = (field.get("nameCode") or {}).get("codeValue")
            if code == "ExternalJobID" and field.get("stringValue"):
                return str(field["stringValue"])
        return str(raw.get("clientRequisitionID") or raw.get("itemID") or "")

    def _portal_url(self, job_id: str) -> str:
        params = self._params()
        params.update({"selectedMenuKey": "CurrentOpenings", "jobId": job_id})
        return f"{self.PORTAL}?{urlencode(params)}"

    def fetch(self, session: requests.Session) -> list[Job]:
        rows: list[dict[str, Any]] = []
        page_size = 100
        for page in range(10):
            data = request_json(
                session,
                "GET",
                self.API,
                params=self._params(top=page_size, skip=page * page_size),
            )
            if not isinstance(data, dict):
                break
            page_rows = data.get("jobRequisitions") or []
            if not page_rows:
                break
            rows.extend(row for row in page_rows if isinstance(row, dict))
            if len(page_rows) < page_size:
                break

        jobs: list[Job] = []
        for raw in rows:
            item_id = str(raw.get("itemID") or "")
            title = raw.get("requisitionTitle")
            if not title or not item_id:
                continue
            detail = request_json(
                session,
                "GET",
                f"{self.API}/{item_id}",
                params=self._params(),
            )
            detail = detail if isinstance(detail, dict) else {}
            external_id = self._external_id(raw)
            work_level = raw.get("workLevelCode") or {}
            category = raw.get("jobCategoryCode") or {}
            jobs.append(
                Job(
                    company=self.company,
                    title=str(title),
                    url=self._portal_url(external_id or item_id),
                    locations=self._locations(raw),
                    source=self.name,
                    ats="adp",
                    posted_date=_date(raw.get("postDate")),
                    description=plain_text(
                        detail.get("requisitionDescription")
                        or raw.get("requisitionDescription")
                    ),
                    department=(
                        category.get("shortName") if isinstance(category, dict) else None
                    ),
                    employment_type=(
                        work_level.get("shortName")
                        if isinstance(work_level, dict)
                        else None
                    ),
                )
            )
        return jobs


class WordPressJobsSource(Source):
    """Scrape a simple WordPress jobs archive and linked job detail pages."""

    def __init__(
        self,
        company: str,
        board_url: str,
        job_path_prefix: str = "/jobs/",
        default_location: str = "",
    ):
        self.company = company
        self.board_url = board_url
        self.job_path_prefix = "/" + job_path_prefix.strip("/") + "/"
        self.default_location = default_location
        self.name = f"wordpress:{company}"

    def fetch(self, session: requests.Session) -> list[Job]:
        html = request_text(session, self.board_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "lxml")
        board_host = urlparse(self.board_url).netloc
        detail_links: dict[str, tuple[str, str]] = {}

        for anchor in soup.find_all("a", href=True):
            url = urljoin(self.board_url, anchor["href"])
            parsed = urlparse(url)
            path = parsed.path
            if parsed.netloc != board_host or not path.startswith(self.job_path_prefix):
                continue
            if path.rstrip("/") == self.job_path_prefix.rstrip("/"):
                continue
            title = _nearest_heading(anchor) or ""
            if not title:
                continue
            container_text = anchor.parent.get_text(" ", strip=True) if anchor.parent else ""
            location = _location_from_text(container_text) or self.default_location
            detail_links[url] = (title, location)

        jobs: list[Job] = []
        for url, (fallback_title, fallback_location) in detail_links.items():
            detail = _detail_from_html(
                request_text(session, url) or "",
                fallback_title=fallback_title,
                fallback_location=fallback_location,
            )
            jobs.append(
                Job(
                    company=self.company,
                    title=detail["title"],
                    url=url,
                    locations=detail["locations"],
                    source=self.name,
                    ats="wordpress",
                    posted_date=detail["posted_date"],
                    description=detail["description"],
                    employment_type=detail["employment_type"],
                )
            )
        return jobs


class CareerPageSource(Source):
    """Scrape job links embedded in a company's ordinary careers page."""

    def __init__(
        self,
        company: str,
        board_url: str,
        job_host: str,
        default_location: str = "",
        follow_details: bool = True,
    ):
        self.company = company
        self.board_url = board_url
        self.job_host = job_host.lower()
        self.default_location = default_location
        self.follow_details = follow_details
        self.name = f"career-page:{company}"

    def fetch(self, session: requests.Session) -> list[Job]:
        html = request_text(session, self.board_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "lxml")
        links: dict[str, tuple[str, str]] = {}
        for anchor in soup.find_all("a", href=True):
            url = urljoin(self.board_url, anchor["href"])
            if self.job_host not in urlparse(url).netloc.lower():
                continue
            title = _nearest_heading(anchor) or ""
            if not title:
                continue
            container = anchor.parent
            text = container.get_text(" ", strip=True) if container else ""
            location = _location_from_text(text) or self.default_location
            links[url] = (title, location)

        jobs: list[Job] = []
        for url, (fallback_title, fallback_location) in links.items():
            detail = {
                "title": fallback_title,
                "description": "",
                "locations": _dedupe([fallback_location]),
                "posted_date": None,
                "employment_type": None,
            }
            if self.follow_details:
                detail = _detail_from_html(
                    request_text(session, url) or "",
                    fallback_title=fallback_title,
                    fallback_location=fallback_location,
                )
            jobs.append(
                Job(
                    company=self.company,
                    title=detail["title"],
                    url=url,
                    locations=detail["locations"],
                    source=self.name,
                    ats="career-page",
                    posted_date=detail["posted_date"],
                    description=detail["description"],
                    employment_type=detail["employment_type"],
                )
            )
        return jobs
