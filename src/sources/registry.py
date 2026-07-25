"""Build all configured job sources."""

from __future__ import annotations

import logging

from .. import config
from ..smart_filters import workday_search_terms
from . import github_lists
from .ashby import AshbySource
from .base import Source
from .direct import (
    ADPSource,
    CareerPageSource,
    JazzHRSource,
    PaylocitySource,
    UKGProSource,
    WordPressJobsSource,
)
from .greenhouse import GreenhouseSource
from .icims import ICIMSSource
from .lever import LeverSource
from .workday import WorkdaySource

log = logging.getLogger(__name__)


def _enabled(entry: dict) -> bool:
    return entry.get("enabled", True) is not False


def build_all_sources() -> list[Source]:
    sources: list[Source] = []

    sources.extend(github_lists.build_sources())
    companies = config.companies()

    for entry in companies.get("greenhouse", []) or []:
        if _enabled(entry) and entry.get("token"):
            sources.append(GreenhouseSource(entry["company"], entry["token"]))

    for entry in companies.get("lever", []) or []:
        if _enabled(entry) and entry.get("token"):
            sources.append(LeverSource(entry["company"], entry["token"]))

    for entry in companies.get("ashby", []) or []:
        if _enabled(entry) and entry.get("token"):
            sources.append(AshbySource(entry["company"], entry["token"]))

    for entry in companies.get("workday", []) or []:
        if _enabled(entry) and entry.get("tenant") and entry.get("site"):
            company = entry["company"]
            intelligence_terms = workday_search_terms(company)
            configured_terms = entry.get("search_texts") or []
            search_terms = (
                configured_terms
                or intelligence_terms
                or [entry.get("search_text", "intern")]
            )
            sources.append(
                WorkdaySource(
                    company,
                    entry["tenant"],
                    entry.get("wd_num", 1),
                    entry["site"],
                    search_texts=search_terms,
                    fetch_details=entry.get(
                        "fetch_details",
                        bool(intelligence_terms),
                    ),
                )
            )

    for entry in companies.get("icims", []) or []:
        if _enabled(entry) and entry.get("company") and entry.get("url"):
            company = entry["company"]
            sources.append(
                ICIMSSource(
                    company=company,
                    url=entry["url"],
                    fetch_details=entry.get(
                        "fetch_details",
                        bool(workday_search_terms(company)),
                    ),
                )
            )

    direct = config.direct_companies()

    for entry in direct.get("jazzhr", []) or []:
        if _enabled(entry) and entry.get("company") and entry.get("board_url"):
            sources.append(
                JazzHRSource(
                    company=entry["company"],
                    board_url=entry["board_url"],
                    default_location=entry.get("default_location", ""),
                )
            )

    for entry in direct.get("paylocity", []) or []:
        if _enabled(entry) and entry.get("company") and entry.get("guid"):
            sources.append(
                PaylocitySource(
                    company=entry["company"],
                    guid=entry["guid"],
                )
            )

    for entry in direct.get("ukg", []) or []:
        required = all(entry.get(key) for key in ("company", "host", "code", "board"))
        if _enabled(entry) and required:
            sources.append(
                UKGProSource(
                    company=entry["company"],
                    host=entry["host"],
                    code=entry["code"],
                    board=entry["board"],
                )
            )

    for entry in direct.get("adp", []) or []:
        if _enabled(entry) and entry.get("company") and entry.get("cid"):
            sources.append(
                ADPSource(
                    company=entry["company"],
                    cid=entry["cid"],
                    cc_id=entry.get("cc_id", "19000101_000001"),
                    lang=entry.get("lang", "en_US"),
                )
            )

    for entry in direct.get("wordpress_jobs", []) or []:
        if _enabled(entry) and entry.get("company") and entry.get("board_url"):
            sources.append(
                WordPressJobsSource(
                    company=entry["company"],
                    board_url=entry["board_url"],
                    job_path_prefix=entry.get("job_path_prefix", "/jobs/"),
                    default_location=entry.get("default_location", ""),
                )
            )

    for entry in direct.get("career_pages", []) or []:
        required = all(entry.get(key) for key in ("company", "board_url", "job_host"))
        if _enabled(entry) and required:
            sources.append(
                CareerPageSource(
                    company=entry["company"],
                    board_url=entry["board_url"],
                    job_host=entry["job_host"],
                    default_location=entry.get("default_location", ""),
                    follow_details=entry.get("follow_details", True),
                )
            )

    log.info("built %d sources", len(sources))
    return sources
