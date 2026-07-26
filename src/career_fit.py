"""Score jobs by whether they build Mohamed's target hardware career skills."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from . import config
from . import filters as base
from .models import Job


@dataclass
class CareerFitResult:
    passed: bool
    score: int
    band: str
    hardware_skill: int
    resume_growth: int
    career_alignment: int
    company_quality: int
    location_fit: int
    evidence: list[str] = field(default_factory=list)
    rejection_reason: str | None = None


@lru_cache(maxsize=1)
def policy() -> dict[str, Any]:
    return config._load_yaml("career_fit.yaml")  # noqa: SLF001


def _text(job: Job) -> tuple[str, str]:
    title = base.normalize_text(getattr(job, "title", "") or "")
    body = base.normalize_text(
        "\n".join(
            str(value)
            for value in (
                getattr(job, "description", None),
                getattr(job, "department", None),
                getattr(job, "team", None),
            )
            if value
        )
    )
    return title, body


def _hits(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if base._term_pattern(base._norm_term(term)).search(text)]  # noqa: SLF001


def _band(score: int, cfg: dict[str, Any]) -> str:
    bands = cfg.get("score_bands") or {}
    if score >= int(bands.get("must_apply", 95)):
        return "must_apply"
    if score >= int(bands.get("excellent", 90)):
        return "excellent"
    if score >= int(bands.get("good", 80)):
        return "good"
    if score >= int(bands.get("selective", 70)):
        return "selective"
    return "reject"


def evaluate(job: Job) -> CareerFitResult:
    cfg = policy()
    title, body = _text(job)
    combined = f"{title}\n{body}"
    category = getattr(job, "category", None) or ""

    hard_rejects = _hits(title, list(cfg.get("hard_reject_title_terms") or []))
    if hard_rejects:
        return CareerFitResult(
            False, 0, "reject", 0, 0, 0, 0, 0,
            evidence=[f"blocked title: {hard_rejects[0]}"],
            rejection_reason="non-hardware career path",
        )

    strong_hits = _hits(combined, list(cfg.get("strong_hardware_terms") or []))
    hands_on_hits = _hits(body, list(cfg.get("hands_on_terms") or []))
    negative_hits = _hits(combined, list(cfg.get("negative_description_terms") or []))
    conditional = bool(_hits(title, list(cfg.get("conditional_title_terms") or [])))

    elite = category in set(cfg.get("elite_categories") or [])
    conditional_category = category in set(cfg.get("conditional_categories") or [])

    # Conditional titles such as process, quality, manufacturing, systems, and
    # field service must prove actual hardware work in the posting.
    if (conditional or conditional_category) and not strong_hits:
        return CareerFitResult(
            False, 25, "reject", 10, 10, 5, 0, 0,
            evidence=["conditional engineering title lacks hardware evidence"],
            rejection_reason="generic engineering title without hardware proof",
        )

    hardware_skill = 0
    if elite:
        hardware_skill += 24
    hardware_skill += min(16, len(strong_hits) * 3)
    hardware_skill = min(40, hardware_skill)

    resume_growth = 5
    if elite:
        resume_growth += 10
    resume_growth += min(10, len(set(strong_hits)) * 2)
    resume_growth += min(5, len(set(hands_on_hits)) * 2)
    resume_growth = min(25, resume_growth)

    career_alignment = 5
    if elite:
        career_alignment += 10
    if strong_hits:
        career_alignment += min(5, len(set(strong_hits)))
    career_alignment = min(20, career_alignment)

    company = base.normalize_text(getattr(job, "company", "") or "")
    preferred_company = any(
        base.normalize_text(name) in company
        for name in cfg.get("preferred_companies") or []
    )
    company_quality = 10 if preferred_company and (elite or strong_hits) else 4 if preferred_company else 0

    location = base.normalize_text(getattr(job, "location_str", "") or "")
    preferred_location = any(
        base.normalize_text(name) in location
        for name in cfg.get("preferred_locations") or []
    )
    location_fit = 5 if preferred_location else 2 if location else 0

    score = hardware_skill + resume_growth + career_alignment + company_quality + location_fit
    score -= min(25, len(negative_hits) * 8)
    score = max(0, min(100, score))
    band = _band(score, cfg)
    minimum = int(cfg.get("minimum_email_score", 70))

    evidence: list[str] = []
    if strong_hits:
        evidence.append("hardware skills: " + ", ".join(strong_hits[:6]))
    if hands_on_hits:
        evidence.append("hands-on work: " + ", ".join(hands_on_hits[:4]))
    if preferred_company:
        evidence.append("target hardware employer")
    if preferred_location:
        evidence.append("preferred Minnesota location")
    if negative_hits:
        evidence.append("career-risk terms: " + ", ".join(negative_hits[:3]))

    return CareerFitResult(
        passed=score >= minimum,
        score=score,
        band=band,
        hardware_skill=hardware_skill,
        resume_growth=resume_growth,
        career_alignment=career_alignment,
        company_quality=company_quality,
        location_fit=location_fit,
        evidence=evidence,
        rejection_reason=None if score >= minimum else "career fit score below threshold",
    )


def apply(job: Job) -> bool:
    result = evaluate(job)
    job.career_fit_score = result.score
    job.career_fit_band = result.band
    job.hardware_skill_score = result.hardware_skill
    job.resume_growth_score = result.resume_growth
    job.career_alignment_score = result.career_alignment
    job.company_quality_score = result.company_quality
    job.location_fit_score = result.location_fit
    job.career_fit_evidence = result.evidence

    if result.passed:
        if result.score >= 95:
            job.priority = "A+"
        elif result.score >= 90:
            job.priority = "A"
        elif result.score >= 80:
            job.priority = "B"
        else:
            job.priority = "C"
        job.hiring_signal = (
            f"Hardware career fit {result.score}/100: "
            f"{result.band.replace('_', ' ')}"
        )
    return result.passed
