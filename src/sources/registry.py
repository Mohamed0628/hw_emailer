"""Build all configured job sources."""

from __future__ import annotations

import logging

from .. import config
from ..smart_filters import workday_search_terms
from . import github_lists
from .ashby import AshbySource
from .base import Source
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

    log.info("built %d sources", len(sources))
    return sources
