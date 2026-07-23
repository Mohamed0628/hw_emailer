"""Filtering: keep US internships and new-grad jobs in our target categories.

A job passes only if it is:
1. An internship or new-grad role.
2. Within an allowed season/year when detectable.
3. In a target category.
4. US-located.

As a side effect, `apply_filters` annotates each kept Job with
`.category`, `.season`, and `.year`.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, Optional

from . import config
from .models import Job


_YEAR_RE = re.compile(r"\b(20\d{2})\b")

# Match entry-level Engineer I titles without accidentally matching
# Engineer II, Engineer III, or Engineer IV.
#
# Accepted examples:
#   Electrical Engineer I
#   Hardware Engineer 1
#   Firmware Engineer Level I
#   Controls Engineer Level 1
_ENGINEER_I_RE = re.compile(
    r"\bengineer\s+(?:level\s+)?(?:1|i)\b(?!\s*i)",
    re.IGNORECASE,
)

# Map detection keywords to canonical season labels.
_SEASON_KEYWORDS = [
    ("summer", "summer"),
    ("spring", "spring"),
    ("autumn", "fall"),
    ("fall", "fall"),
    ("winter", "winter"),
    ("off-cycle", "offcycle"),
    ("off cycle", "offcycle"),
    ("offcycle", "offcycle"),
]

_FULLTIME_VARIANTS = {"full-time", "full time", "fulltime"}


def _lc(s: str) -> str:
    """Return a lowercase string, safely handling empty values."""
    return (s or "").lower()


def _contains_any(text: str, terms: Iterable[str]) -> bool:
    """Return True when any configured term occurs in the text."""
    return any(term in text for term in terms)


@lru_cache(maxsize=8)
def _loc_regex(terms: tuple[str, ...]):
    """Compile location terms into one alternation.

    This prevents short location terms from matching inside longer words.
    For example, ", ca" can match "San Jose, CA" without matching "Canada".
    """
    if not terms:
        return None

    pattern = "(?:" + "|".join(re.escape(term) for term in terms) + ")(?![a-z])"
    return re.compile(pattern)


def _loc_match(text: str, terms: Iterable[str]) -> bool:
    """Return True when the location text matches a configured term."""
    rx = _loc_regex(tuple(terms))
    return bool(rx.search(text)) if rx else False


def detect_season(job: Job) -> Optional[str]:
    """Detect and normalize a job's season."""
    if job.season:
        season = job.season.lower()

        for keyword, canonical in _SEASON_KEYWORDS:
            if keyword in season:
                return canonical

        return season

    title = _lc(job.title)

    for keyword, canonical in _SEASON_KEYWORDS:
        if keyword in title:
            return canonical

    return None


def detect_year(job: Job) -> Optional[int]:
    """Detect a four-digit year from the job title."""
    if job.year:
        return job.year

    match = _YEAR_RE.search(job.title or "")
    return int(match.group(1)) if match else None


def _hard_excludes(role_cfg: dict) -> list[str]:
    """Return seniority exclusions shared by internships and new-grad roles."""
    return [
        term.lower()
        for term in role_cfg.get("exclude_terms", [])
        if term.lower() not in _FULLTIME_VARIANTS
    ]


def is_internship(title_lc: str, role_cfg: dict) -> bool:
    """Return True if the title looks like an internship."""
    internship_terms = [
        term.lower()
        for term in role_cfg.get("internship_terms", [])
    ]

    if not _contains_any(title_lc, internship_terms):
        return False

    if _contains_any(title_lc, _hard_excludes(role_cfg)):
        return False

    return True


def is_engineer_i(title_lc: str) -> bool:
    """Return True for Engineer I or Engineer 1 titles.

    The regex deliberately avoids matching higher levels such as
    Engineer II, Engineer III, or Engineer IV.
    """
    return bool(_ENGINEER_I_RE.search(title_lc))


def is_new_grad(title_lc: str, role_cfg: dict) -> bool:
    """Return True if the title looks like a new-grad or early-career role."""
    new_grad_terms = [
        term.lower()
        for term in role_cfg.get("new_grad_terms", [])
    ]

    has_new_grad_term = _contains_any(title_lc, new_grad_terms)
    has_engineer_i_title = is_engineer_i(title_lc)

    if not has_new_grad_term and not has_engineer_i_title:
        return False

    if _contains_any(title_lc, _hard_excludes(role_cfg)):
        return False

    return True


def classify_category(
    title_lc: str,
    categories_cfg: dict,
) -> Optional[str]:
    """Classify a job using the first matching configured category."""
    for category, terms in categories_cfg.items():
        normalized_terms = [term.lower() for term in terms]

        if _contains_any(title_lc, normalized_terms):
            return category

    return None


def is_us_location(job: Job, loc_cfg: dict) -> bool:
    """Return True if the job has an accepted US location."""
    if not loc_cfg.get("require_us", True):
        return True

    text = _lc(job.location_str)

    if not text.strip():
        return bool(loc_cfg.get("keep_when_location_unknown", True))

    us_terms = [
        term.lower()
        for term in loc_cfg.get("us_terms", [])
    ]

    non_us_terms = [
        term.lower()
        for term in loc_cfg.get("non_us_terms", [])
    ]

    has_us = _loc_match(text, us_terms)
    has_non_us = _loc_match(text, non_us_terms)

    # Keep multi-location postings when at least one US option exists.
    if has_us:
        return True

    if has_non_us:
        return False

    return bool(loc_cfg.get("keep_when_location_unknown", True))


def passes(job: Job, f: dict) -> bool:
    """Return True if a job should be kept and annotate it in place."""
    title_lc = _lc(job.title)
    role_cfg = f.get("role", {})
    loc_cfg = f.get("location", {})

    # 1. Internship or new-grad role.
    internship = is_internship(title_lc, role_cfg)
    new_grad = is_new_grad(title_lc, role_cfg)

    allow_internships = role_cfg.get("allow_internships", True)
    allow_new_grad = role_cfg.get("allow_new_grad", False)

    accepted_role = (
        (allow_internships and internship)
        or (allow_new_grad and new_grad)
    )

    if not accepted_role:
        return False

    # 2. Season window.
    season = detect_season(job)
    allowed_seasons = [
        season_name.lower()
        for season_name in role_cfg.get("seasons", [])
    ]

    if allowed_seasons and season and season not in allowed_seasons:
        return False

    job.season = season

    # 3. Year window.
    year = detect_year(job)
    allowed_years = role_cfg.get("years", [])

    if allowed_years and year and year not in allowed_years:
        return False

    job.year = year

    # 4. Category.
    category = classify_category(
        title_lc,
        f.get("categories", {}),
    )

    if f.get("require_category", True) and not category:
        return False

    job.category = category or "other"

    # 5. US location.
    if not is_us_location(job, loc_cfg):
        return False

    return True


def apply_filters(
    jobs: list[Job],
    f: Optional[dict] = None,
) -> list[Job]:
    """Apply the configured filters to a list of jobs."""
    filters_config = f if f is not None else config.filters()
    return [job for job in jobs if passes(job, filters_config)]