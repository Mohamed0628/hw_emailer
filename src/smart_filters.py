"""Description-aware filtering for internships and full-time early-career roles.

The existing title filter remains the source of truth for internships and
explicit new-grad titles. This module adds a conservative fallback for ordinary
titles such as "Electrical Engineer" or "R&D Engineer II" when the posting
itself proves that a bachelor's graduate with 0-2 years is eligible.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Optional

from . import config
from . import filters as base
from .models import Job

_HARD_SENIORITY_RE = re.compile(
    r"\b(?:senior|sr|staff|principal|lead|manager|director|architect|"
    r"distinguished|fellow|chief|supervisor|vice president|vp|head)\b",
    re.IGNORECASE,
)
_LEVEL_II_RE = re.compile(r"\bengineer\s+(?:level\s+)?(?:ii|2)\b", re.IGNORECASE)
_LEVEL_III_PLUS_RE = re.compile(
    r"\bengineer\s+(?:level\s+)?(?:iii|iv|v|vi|3|4|5|6|7|8|9)\b",
    re.IGNORECASE,
)
_TECHNICAL_TITLE_RE = re.compile(
    r"\b(?:electrical|electronics?|hardware|firmware|embedded|systems?|test|"
    r"verification|validation|product|r\s*&\s*d|research|manufacturing|"
    r"process|quality|reliability|automation|controls?|robotics?|"
    r"mechatronics?|power|design|sustaining)\b.*\bengineer(?:ing)?\b|"
    r"\bengineer(?:ing)?\b.*\b(?:electrical|electronics?|hardware|firmware|"
    r"embedded|systems?|test|verification|validation|product|r\s*&\s*d|"
    r"research|manufacturing|process|quality|reliability|automation|controls?|"
    r"robotics?|mechatronics?|power|design|sustaining)\b",
    re.IGNORECASE,
)
_DIRECT_EE_TITLE_RE = re.compile(
    r"\b(?:electrical|electronics?|hardware|firmware|embedded|pcb|circuit|"
    r"analog|digital|mixed[- ]signal|fpga|power electronics|motor control|"
    r"controls?|automation|robotics?|mechatronics?|instrumentation|rf|"
    r"signal integrity|power integrity|emc|emi)\b",
    re.IGNORECASE,
)
_ADJACENT_ENGINEERING_TITLE_RE = re.compile(
    r"\b(?:systems?|test|verification|validation|product|r\s*&\s*d|research|"
    r"reliability|sustaining|manufacturing|process development|quality)\b",
    re.IGNORECASE,
)
_BUSINESS_OR_TRADE_RE = re.compile(
    r"\b(?:technician|mechanic|machinist|welder|product manager|project manager|"
    r"program manager|marketing|sales|finance|accounting|recruiter|human resources|"
    r"supply chain|procurement|logistics|clinical specialist|nurse|physician)\b",
    re.IGNORECASE,
)
_PLAIN_SOFTWARE_RE = re.compile(
    r"\b(?:software|frontend|backend|full stack|web developer|mobile developer|"
    r"ios|android|data scientist|data analyst|machine learning|cloud|devops|"
    r"cybersecurity)\b",
    re.IGNORECASE,
)
_SOFTWARE_HARDWARE_ALLOW_RE = re.compile(
    r"\b(?:embedded|firmware|device software|rtos|bare metal|driver|bsp|fpga|"
    r"hardware|controls?|real time|avionics|hil)\b",
    re.IGNORECASE,
)

_EXPLICIT_ENTRY_RE = re.compile(
    r"\b(?:entry[- ]level|early[- ]career|new grad(?:uate)?|recent grad(?:uate)?|"
    r"college grad(?:uate)?|university grad(?:uate)?|campus hire|"
    r"no (?:prior|previous|professional) experience required)\b",
    re.IGNORECASE,
)
_CLOSE_SUPERVISION_RE = re.compile(
    r"\b(?:under (?:close|direct) supervision|receives (?:close )?guidance|"
    r"routine assignments|limited professional experience)\b",
    re.IGNORECASE,
)
_INTERN_PREFERRED_RE = re.compile(
    r"\b(?:internship|co[- ]?op) experience (?:is )?(?:preferred|desired|a plus)\b",
    re.IGNORECASE,
)
_BACHELOR_RE = re.compile(
    r"\b(?:bachelor(?:'s|s)?|b\.?s\.?|undergraduate degree)\b",
    re.IGNORECASE,
)
_MASTER_RE = re.compile(r"\b(?:master(?:'s|s)?|m\.?s\.?)\b", re.IGNORECASE)
_PREFERRED_RE = re.compile(
    r"\b(?:preferred|desired|nice to have|ideally|a plus)\b",
    re.IGNORECASE,
)
_REQUIRED_RE = re.compile(
    r"\b(?:required|minimum|at least|must|basic qualification)\b",
    re.IGNORECASE,
)

_EXPERIENCE_RANGE_RE = re.compile(
    r"(?P<lo>\d+)\s*(?:-|to|through)\s*(?P<hi>\d+)\s+years?"
    r"(?:\s+of)?(?:\s+[a-z0-9/+&-]+){0,7}\s+experience",
    re.IGNORECASE,
)
_EXPERIENCE_PLUS_RE = re.compile(
    r"(?P<lo>\d+)\s*\+\s*years?(?:\s+of)?"
    r"(?:\s+[a-z0-9/+&-]+){0,7}\s+experience",
    re.IGNORECASE,
)
_EXPERIENCE_SINGLE_RE = re.compile(
    r"(?:minimum of|at least|requires?|with|and)?\s*(?P<lo>\d+)\s+years?"
    r"(?:\s+of)?(?:\s+[a-z0-9/+&-]+){0,7}\s+experience",
    re.IGNORECASE,
)
_ZERO_EXPERIENCE_RE = re.compile(
    r"\b(?:0|zero)\s+years?(?:\s+of)?"
    r"(?:\s+[a-z0-9/+&-]+){0,7}\s+experience\b|"
    r"\bno (?:prior|previous|professional) experience required\b",
    re.IGNORECASE,
)


@dataclass
class EntryLevelAssessment:
    eligible: bool
    score: int = 0
    evidence: list[str] = field(default_factory=list)
    rejection_reason: Optional[str] = None
    bachelor_min_years: Optional[int] = None
    general_min_years: Optional[int] = None


@dataclass
class SmartFilterResult:
    passed: bool
    role_type: Optional[str] = None
    category: Optional[str] = None
    season: Optional[str] = None
    year: Optional[int] = None
    location_passed: Optional[bool] = None
    entry_level_score: int = 0
    evidence: list[str] = field(default_factory=list)
    priority: Optional[str] = None
    hiring_signal: Optional[str] = None
    rejection_reason: Optional[str] = None


def _job_text(job: Job) -> str:
    parts = [
        getattr(job, "description", None),
        getattr(job, "department", None),
        getattr(job, "team", None),
    ]
    return "\n".join(str(value) for value in parts if value)


def _normalized_experience_text(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    return re.sub(r"[ \t]+", " ", text)


def _is_preferred_only(text: str, start: int, end: int) -> bool:
    """Return True when a matched experience number is only a preference."""
    left = max(0, start - 100)
    right = min(len(text), end + 100)
    window = text[left:right]
    return bool(_PREFERRED_RE.search(window) and not _REQUIRED_RE.search(window))


def _experience_mins(text: str) -> list[int]:
    """Return minimum years from required or neutral experience statements."""
    mins: list[int] = []
    for pattern in (
        _EXPERIENCE_RANGE_RE,
        _EXPERIENCE_PLUS_RE,
        _EXPERIENCE_SINGLE_RE,
    ):
        for match in pattern.finditer(text):
            if _is_preferred_only(text, match.start(), match.end()):
                continue
            try:
                mins.append(int(match.group("lo")))
            except (TypeError, ValueError):
                continue
    if _ZERO_EXPERIENCE_RE.search(text):
        mins.append(0)
    return mins


def _degree_window_mins(text: str, degree_re: re.Pattern[str]) -> list[int]:
    """Find experience minima in the same degree alternative."""
    mins: list[int] = []
    clauses = re.split(r"\b(?:or|and/or)\b|[;\n]", text, flags=re.IGNORECASE)
    for clause in clauses:
        if degree_re.search(clause):
            mins.extend(_experience_mins(clause))
    return mins


def assess_entry_level(job: Job, role_cfg: dict[str, Any]) -> EntryLevelAssessment:
    """Conservatively infer bachelor's-level early-career eligibility."""
    title = getattr(job, "title", "") or ""
    description = _normalized_experience_text(_job_text(job))
    score = 0
    evidence: list[str] = []

    title_is_explicit = base.is_new_grad(title, role_cfg)
    engineer_i = base.is_engineer_i(title)
    if title_is_explicit:
        score += 6
        evidence.append("explicit early-career title")
    if engineer_i:
        score += 6
        evidence.append("Engineer I title")

    bachelor_mins = _degree_window_mins(description, _BACHELOR_RE)
    general_mins = _experience_mins(description)
    bachelor_min = min(bachelor_mins) if bachelor_mins else None
    general_min = min(general_mins) if general_mins else None

    if bachelor_min is not None:
        if bachelor_min <= 2:
            score += 5
            evidence.append(f"bachelor's path allows {bachelor_min}-2 years")
        else:
            return EntryLevelAssessment(
                False,
                score=score,
                evidence=evidence,
                rejection_reason=f"bachelor's path requires {bachelor_min}+ years",
                bachelor_min_years=bachelor_min,
                general_min_years=general_min,
            )
    elif general_min is not None:
        has_degree_alternatives = bool(
            _BACHELOR_RE.search(description) and _MASTER_RE.search(description)
        )
        if general_min <= 2 and not has_degree_alternatives:
            score += 4
            evidence.append(f"description allows {general_min}-2 years")
        elif general_min >= 3:
            return EntryLevelAssessment(
                False,
                score=score,
                evidence=evidence,
                rejection_reason=f"description requires {general_min}+ years",
                bachelor_min_years=bachelor_min,
                general_min_years=general_min,
            )

    if _EXPLICIT_ENTRY_RE.search(description):
        score += 5
        evidence.append("explicit entry-level description")
    if _ZERO_EXPERIENCE_RE.search(description):
        score += 5
        evidence.append("no experience required")
    if _CLOSE_SUPERVISION_RE.search(description):
        score += 2
        evidence.append("close-supervision language")
    if _INTERN_PREFERRED_RE.search(description):
        score += 1
        evidence.append("internship experience preferred")
    if _BACHELOR_RE.search(description):
        score += 1
        evidence.append("bachelor's degree accepted")

    if _LEVEL_II_RE.search(title):
        proven = (
            bachelor_min is not None and bachelor_min <= 2
        ) or (
            bachelor_min is None
            and general_min is not None
            and general_min <= 2
            and not (
                _BACHELOR_RE.search(description)
                and _MASTER_RE.search(description)
            )
        ) or bool(_ZERO_EXPERIENCE_RE.search(description))
        if not proven:
            return EntryLevelAssessment(
                False,
                score=score,
                evidence=evidence,
                rejection_reason=(
                    "Engineer II lacks a proven bachelor's 0-2 year path"
                ),
                bachelor_min_years=bachelor_min,
                general_min_years=general_min,
            )
        score += 2
        evidence.append("Engineer II verified at 0-2 years")

    eligible = title_is_explicit or engineer_i or score >= 5
    return EntryLevelAssessment(
        eligible,
        score=score,
        evidence=evidence,
        rejection_reason=(
            None if eligible else "insufficient early-career evidence"
        ),
        bachelor_min_years=bachelor_min,
        general_min_years=general_min,
    )


@lru_cache(maxsize=1)
def _intelligence() -> dict[str, Any]:
    return config.minnesota_medtech()


def _company_match(job: Job) -> tuple[Optional[str], dict[str, Any]]:
    company = base.normalize_text(getattr(job, "company", "") or "")
    if not company:
        return None, {}
    for canonical, spec in (_intelligence().get("companies") or {}).items():
        aliases = [canonical, *(spec.get("aliases") or [])]
        for alias in aliases:
            normalized_alias = base.normalize_text(str(alias))
            if normalized_alias and (
                normalized_alias == company
                or normalized_alias in company
                or company in normalized_alias
            ):
                return canonical, spec or {}
    return None, {}


def _augmented_filters(f: dict[str, Any]) -> dict[str, Any]:
    """Add Minnesota medtech company context without mutating base config."""
    out = copy.deepcopy(f)
    aliases = out.setdefault("company_aliases", {})
    defaults = _intelligence().get("defaults") or {}
    category = defaults.get("category", "medtech_hardware")
    include_terms = list(defaults.get("include_terms") or [])
    for canonical, spec in (_intelligence().get("companies") or {}).items():
        alias_spec = {
            "category": spec.get("category", category),
            "include_terms": list(spec.get("include_terms") or include_terms),
        }
        for alias in [canonical, *(spec.get("aliases") or [])]:
            aliases.setdefault(str(alias), alias_spec)
    return out


def workday_search_terms(company: str) -> list[str]:
    """Return full-time search terms for a known medtech employer."""
    placeholder = type("_Company", (), {"company": company})()
    canonical, spec = _company_match(placeholder)  # type: ignore[arg-type]
    if not canonical:
        return []
    defaults = _intelligence().get("defaults") or {}
    return list(
        spec.get("workday_search_terms")
        or defaults.get("workday_search_terms")
        or []
    )


def potential_technical_title(title: str) -> bool:
    """Cheap title screen used before downloading a full ATS description."""
    if _HARD_SENIORITY_RE.search(title) or _LEVEL_III_PLUS_RE.search(title):
        return False
    if _BUSINESS_OR_TRADE_RE.search(title):
        return False
    if _PLAIN_SOFTWARE_RE.search(title) and not _SOFTWARE_HARDWARE_ALLOW_RE.search(title):
        return False
    normalized = base.normalize_text(title)
    return bool(
        _TECHNICAL_TITLE_RE.search(title)
        or _LEVEL_II_RE.search(title)
        or base.is_engineer_i(normalized)
        or base.is_internship(normalized, {"internship_terms": [], "exclude_terms": []})
        or _EXPLICIT_ENTRY_RE.search(title)
    )


def _priority_for(
    job: Job,
    category: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    canonical, spec = _company_match(job)
    if not canonical:
        return None, None

    title = getattr(job, "title", "") or ""
    location = base.normalize_text(getattr(job, "location_str", "") or "")
    is_minnesota = any(
        term in location
        for term in (
            "minnesota",
            " mn",
            "minneapolis",
            "saint paul",
            "st paul",
            "maple grove",
            "plymouth",
            "arden hills",
            "brooklyn park",
        )
    )
    seasonal = datetime.now().month in set(
        spec.get("seasonal_boost_months") or []
    )

    direct_categories = {
        "silicon",
        "hardware",
        "firmware",
        "pcb_hardware",
        "embedded_firmware",
        "electrical",
        "power_electronics",
        "robotics_controls",
        "semiconductor",
    }
    direct = bool(
        category in direct_categories or _DIRECT_EE_TITLE_RE.search(title)
    )
    adjacent = bool(_ADJACENT_ENGINEERING_TITLE_RE.search(title))

    if is_minnesota and direct:
        priority = "A"
        reason = "direct EE or hardware role in Minnesota"
    elif direct:
        priority = "B"
        reason = "direct EE or hardware role at a Minnesota medtech employer"
    elif is_minnesota and adjacent:
        priority = "B"
        reason = "EE-adjacent engineering role in Minnesota"
    else:
        priority = "C"
        reason = "general early-career medtech engineering role"

    if seasonal:
        reason += " during a seasonal hiring boost"
    return priority, f"{canonical}: {reason}"


def _smart_evaluate(job: Job, f: dict[str, Any]) -> SmartFilterResult:
    augmented = _augmented_filters(f)
    role_cfg = augmented.get("role", {})
    location_cfg = augmented.get("location", {})

    legacy = base._evaluate(job, augmented)  # noqa: SLF001
    if legacy.passed:
        assessment = EntryLevelAssessment(True)
        if legacy.role_type == "new_grad":
            assessment = assess_entry_level(job, role_cfg)
            if not assessment.eligible:
                return SmartFilterResult(
                    False,
                    role_type=legacy.role_type,
                    entry_level_score=assessment.score,
                    evidence=assessment.evidence,
                    rejection_reason=assessment.rejection_reason,
                )
        priority, hiring_signal = _priority_for(job, legacy.category)
        return SmartFilterResult(
            True,
            role_type=legacy.role_type,
            category=legacy.category,
            season=legacy.season,
            year=legacy.year,
            location_passed=legacy.location_passed,
            entry_level_score=assessment.score,
            evidence=assessment.evidence,
            priority=priority,
            hiring_signal=hiring_signal,
        )

    if not role_cfg.get("allow_new_grad", False):
        return SmartFilterResult(
            False,
            rejection_reason=legacy.rejection_reason or "new_grad_disabled",
        )

    title = getattr(job, "title", "") or ""
    if not potential_technical_title(title):
        return SmartFilterResult(
            False,
            rejection_reason=legacy.rejection_reason or "title_not_eligible",
        )

    assessment = assess_entry_level(job, role_cfg)
    if not assessment.eligible:
        return SmartFilterResult(
            False,
            role_type="new_grad",
            entry_level_score=assessment.score,
            evidence=assessment.evidence,
            rejection_reason=assessment.rejection_reason,
        )

    season = base.detect_season(job)
    allowed_seasons = [str(value).lower() for value in role_cfg.get("seasons", ())]
    if allowed_seasons and season and season not in allowed_seasons:
        return SmartFilterResult(
            False,
            role_type="new_grad",
            season=season,
            rejection_reason="season",
        )

    year = base.detect_year(job)
    allowed_years = role_cfg.get("years", ())
    if allowed_years and year and year not in allowed_years:
        return SmartFilterResult(
            False,
            role_type="new_grad",
            season=season,
            year=year,
            rejection_reason="year",
        )

    normalized_title = base.normalize_text(title)
    category, matched = base._classify_job(  # noqa: SLF001
        job,
        augmented,
        normalized_title,
    )
    if augmented.get("require_category", True) and not category:
        return SmartFilterResult(
            False,
            role_type="new_grad",
            season=season,
            year=year,
            entry_level_score=assessment.score,
            evidence=assessment.evidence,
            rejection_reason="category",
        )
    if matched:
        assessment.evidence.append("category: " + ", ".join(matched[:3]))

    location_passed = base.is_us_location(job, location_cfg)
    if not location_passed:
        return SmartFilterResult(
            False,
            role_type="new_grad",
            category=category,
            season=season,
            year=year,
            location_passed=False,
            entry_level_score=assessment.score,
            evidence=assessment.evidence,
            rejection_reason="location",
        )

    priority, hiring_signal = _priority_for(job, category)
    return SmartFilterResult(
        True,
        role_type="new_grad",
        category=category or "other",
        season=season,
        year=year,
        location_passed=True,
        entry_level_score=assessment.score,
        evidence=assessment.evidence,
        priority=priority,
        hiring_signal=hiring_signal,
    )


def passes(job: Job, f: Optional[dict[str, Any]] = None) -> bool:
    """Return True for a matching internship or proven early-career role."""
    filters_config = f if f is not None else config.filters()
    result = _smart_evaluate(job, filters_config)
    if not result.passed:
        return False

    job.category = result.category or "other"
    job.season = result.season
    job.year = result.year
    job.role_type = result.role_type
    job.entry_level_score = result.entry_level_score
    job.entry_level_evidence = result.evidence
    job.priority = result.priority
    job.hiring_signal = result.hiring_signal
    return True


def explain_pass(
    job: Job,
    f: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Explain the exact smart-filter outcome without mutating the job."""
    filters_config = f if f is not None else config.filters()
    result = _smart_evaluate(job, filters_config)
    return {
        "passed": result.passed,
        "role_type": result.role_type,
        "category": result.category,
        "season": result.season,
        "year": result.year,
        "location_passed": result.location_passed,
        "entry_level_score": result.entry_level_score,
        "entry_level_evidence": result.evidence,
        "priority": result.priority,
        "hiring_signal": result.hiring_signal,
        "rejection_reason": result.rejection_reason,
    }


def apply_filters(
    jobs: list[Job],
    f: Optional[dict[str, Any]] = None,
) -> list[Job]:
    """Apply smart filtering to all collected jobs."""
    filters_config = f if f is not None else config.filters()
    return [job for job in jobs if passes(job, filters_config)]
