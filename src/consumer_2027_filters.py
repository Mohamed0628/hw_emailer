"""Additive filtering for consumer-electronics roles beginning in 2027.

The normal smart filter remains the primary filter. This module only rescues a
rejected posting when it is a technical US role and either:

1. It comes from the trusted 2027 US new-graduate feed, or
2. It belongs to a configured consumer-hardware or robotics employer and its
   title or description explicitly connects 2027 to a start or graduation cohort.

Every ordinary or rescued match must also pass the hardware career outcome
filter. Famous employers and broad engineering titles cannot bypass that gate.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any, Optional

from . import career_fit
from . import config
from . import filters as base
from . import smart_filters as existing
from .models import Job

_TRUSTED_2027_SOURCE = "githublist:speedyapply-2027-new-grad-usa"
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_COHORT_CONTEXT_RE = re.compile(
    r"\b(?:"
    r"class\s+of|"
    r"graduat(?:e|es|ed|ing|ion)(?:\s+date)?|"
    r"available\s+to\s+start|"
    r"start(?:ing)?(?:\s+date)?|"
    r"begin(?:ning)?|"
    r"join(?:ing)?|"
    r"new\s+grad(?:uate)?|"
    r"university\s+graduate|"
    r"college\s+graduate|"
    r"campus\s+hire|"
    r"cohort"
    r")\b",
    re.IGNORECASE,
)


def _job_text(job: Job) -> str:
    return "\n".join(
        str(value)
        for value in (
            getattr(job, "title", None),
            getattr(job, "description", None),
            getattr(job, "department", None),
            getattr(job, "team", None),
        )
        if value
    )


@lru_cache(maxsize=1)
def _target_companies() -> frozenset[str]:
    """Return normalized companies from every consumer-hardware catalog."""
    names: set[str] = set()
    for catalog in (
        "companies_robotics_consumer_hardware.yaml",
        "companies_consumer_hardware_more.yaml",
    ):
        payload = config._load_yaml(catalog)  # noqa: SLF001
        for entries in payload.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or not entry.get("company"):
                    continue
                normalized = base.normalize_text(str(entry["company"]))
                if normalized:
                    names.add(normalized)
    return frozenset(names)


def _is_target_company(job: Job) -> bool:
    company = base.normalize_text(getattr(job, "company", "") or "")
    if not company:
        return False
    for target in _target_companies():
        if company == target or target in company or company in target:
            return True
    return False


def detect_2027_cohort(job: Job) -> Optional[int]:
    """Detect a recruiting year tied to a start or graduation cohort."""
    if (
        getattr(job, "source", "") == _TRUSTED_2027_SOURCE
        and getattr(job, "year", None)
    ):
        return int(job.year)

    title = getattr(job, "title", "") or ""
    title_years = [int(match.group(1)) for match in _YEAR_RE.finditer(title)]
    if title_years:
        return max(title_years)

    text = _job_text(job)
    years: list[int] = []
    for context in _COHORT_CONTEXT_RE.finditer(text):
        left = max(0, context.start() - 80)
        right = min(len(text), context.end() + 80)
        window = text[left:right]
        years.extend(int(match.group(1)) for match in _YEAR_RE.finditer(window))
    return max(years) if years else None


def _allowed_experience(job: Job, role_cfg: dict[str, Any]):
    """Allow unknown experience, but preserve every hard smart-filter rejection."""
    assessment = existing.assess_entry_level(job, role_cfg)
    if assessment.eligible:
        return assessment
    if assessment.rejection_reason == "insufficient early-career evidence":
        return assessment
    return None


def _rescue_2027_consumer_role(job: Job, filters_config: dict[str, Any]) -> bool:
    role_cfg = filters_config.get("role", {})
    if not role_cfg.get("allow_new_grad", False):
        return False

    trusted_feed = (
        getattr(job, "source", "") == _TRUSTED_2027_SOURCE
        and getattr(job, "role_type", None) == "new_grad"
    )
    if not trusted_feed and not _is_target_company(job):
        return False

    cohort_year = detect_2027_cohort(job)
    if cohort_year != 2027:
        return False

    allowed_years = {int(year) for year in role_cfg.get("years", ())}
    if allowed_years and cohort_year not in allowed_years:
        return False

    title = getattr(job, "title", "") or ""
    if not existing.potential_technical_title(title):
        return False

    assessment = _allowed_experience(job, role_cfg)
    if assessment is None:
        return False

    normalized_title = base.normalize_text(title)
    category, matched = base._classify_job(  # noqa: SLF001
        job,
        filters_config,
        normalized_title,
    )
    if filters_config.get("require_category", True) and not category:
        return False

    if not base.is_us_location(job, filters_config.get("location", {})):
        return False

    evidence = list(assessment.evidence)
    evidence.append("2027 start or graduation cohort")
    if trusted_feed:
        evidence.append("trusted 2027 US new-grad feed")
    if matched:
        evidence.append("category: " + ", ".join(matched[:3]))

    job.category = category or "other"
    job.year = 2027
    job.role_type = "new_grad"
    job.entry_level_score = assessment.score + 5
    job.entry_level_evidence = evidence

    # A trusted source is not enough. The role still has to build target
    # electrical or hardware skills.
    return career_fit.apply(job)


def passes(job: Job, f: Optional[dict[str, Any]] = None) -> bool:
    """Keep only qualified roles that also advance a hardware career."""
    filters_config = f if f is not None else config.filters()
    if existing.passes(job, filters_config):
        return career_fit.apply(job)
    return _rescue_2027_consumer_role(job, filters_config)


def apply_filters(
    jobs: list[Job],
    f: Optional[dict[str, Any]] = None,
) -> list[Job]:
    """Apply early-career eligibility and the hardware career outcome gate."""
    filters_config = f if f is not None else config.filters()
    return [job for job in jobs if passes(job, filters_config)]
