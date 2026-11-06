"""Application-location policy for guarded live runs.

Discovery remains broad. Auto-apply is narrower: it uses configured target markets.
Legacy recovered jobs often lack structured locations, so this module can infer a
target market conservatively from the title, URL, and the beginning of the stored
posting text without reopening the page.
"""
from __future__ import annotations

import re
from urllib.parse import unquote

from .apply.policy import settings
from .models import Job

_MARKET_PATTERNS = {
    "Minnesota": re.compile(
        r"\bMinnesota\b|,\s*MN\b|\b(?:Minneapolis|Saint Paul|St\.? Paul|"
        r"Bloomington|Eden Prairie|Maple Grove|Maplewood|Plymouth|Shakopee|"
        r"Brooklyn Park|Burnsville|Shoreview|St\.? Louis Park)\b",
        re.I,
    ),
    "California": re.compile(
        r"\bCalifornia\b|,\s*CA\b|\b(?:San Francisco|Bay Area|Palo Alto|"
        r"Mountain View|Menlo Park|Sunnyvale|San Jose|Los Angeles|San Diego|"
        r"Santa Clara|Irvine|El Segundo|Hawthorne|Pasadena)\b",
        re.I,
    ),
    "Seattle/Washington": re.compile(
        r",\s*WA\b|\bWashington State\b|\b(?:Seattle|Bellevue|Redmond|"
        r"Everett|Kirkland|Bothell|Renton)\b",
        re.I,
    ),
    "New York": re.compile(
        r"\bNew York\b|,\s*NY\b|\bNYC\b|\b(?:Brooklyn|Queens|Manhattan)\b",
        re.I,
    ),
}


def configured_markets() -> tuple[str, ...]:
    configured = settings().get("target_markets") or tuple(_MARKET_PATTERNS)
    return tuple(str(x) for x in configured if str(x) in _MARKET_PATTERNS)


def _matches(text: str) -> list[str]:
    if not text:
        return []
    return [
        market
        for market in configured_markets()
        if _MARKET_PATTERNS[market].search(text)
    ]


def target_markets(job: Job) -> list[str]:
    """Return configured target markets supported by job location evidence."""
    if job.locations:
        return _matches(job.location_str)

    # Legacy recovery saved the visible posting body but not the separate
    # structured location field. Location labels on ATS pages normally appear
    # near the top; restricting the body window avoids pay-transparency/footer
    # location lists being mistaken for the job's actual location.
    header_text = (job.description or "")[:1800]
    fallback = "\n".join((job.title or "", unquote(job.url or ""), header_text))
    return _matches(fallback)


def target_market(job: Job) -> str | None:
    markets = target_markets(job)
    return markets[0] if markets else None


def enrich_missing_target_location(job: Job) -> Job:
    """Attach conservative inferred target locations to legacy recovered jobs."""
    if job.locations:
        return job
    markets = target_markets(job)
    if not markets:
        return job
    return job.model_copy(update={"locations": [f"{market} (inferred from posting)" for market in markets]})


def auto_apply_location_allowed(job: Job) -> bool:
    if not settings().get("require_target_market_for_auto_apply", False):
        return True
    return bool(target_markets(job))
