"""Build all configured job sources."""

from __future__ import annotations

import logging

from .. import config
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

    # 1) Community internship aggregators.
    sources.extend(github_lists.build_sources())

    # 2) Company ATS APIs.
    comp = config.companies()

    for e in comp.get("greenhouse", []) or []:
        if _enabled(e) and e.get("token"):
            sources.append(GreenhouseSource(e["company"], e["token"]))

    for e in comp.get("lever", []) or []:
        if _enabled(e) and e.get("token"):
            sources.append(LeverSource(e["company"], e["token"]))

    for e in comp.get("ashby", []) or []:
        if _enabled(e) and e.get("token"):
            sources.append(AshbySource(e["company"], e["token"]))

    for e in comp.get("workday", []) or []:
        if _enabled(e) and e.get("tenant") and e.get("site"):
            sources.append(
                WorkdaySource(
                    e["company"],
                    e["tenant"],
                    e.get("wd_num", 1),
                    e["site"],
                )
            )

    for e in comp.get("icims", []) or []:
        if _enabled(e) and e.get("company") and e.get("url"):
            sources.append(
                ICIMSSource(
                    company=e["company"],
                    url=e["url"],
                )
            )

    log.info("built %d sources", len(sources))
    return sources
