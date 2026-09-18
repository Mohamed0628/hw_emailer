"""Explainable hardware-first career scoring shared by discovery and applying."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache

from . import config
from .models import Job
from .signals import features, hits, is_minnesota, vocabulary


@dataclass
class CareerFitResult:
    passed: bool
    score: int
    band: str
    hardware_skill: int = 0
    resume_growth: int = 0
    career_alignment: int = 0
    company_quality: int = 0
    location_fit: int = 0
    evidence: list[str] = field(default_factory=list)
    rejection_reason: str | None = None
    entry_level: int = 0
    supporting_embedded: list[str] = field(default_factory=list)
    software_dominance: list[str] = field(default_factory=list)
    domains: dict[str, list[str]] = field(default_factory=dict)


@lru_cache(maxsize=1)
def policy() -> dict:
    return config._load_yaml("career_fit.yaml")


def _reject(reason: str, evidence: list[str] | None = None) -> CareerFitResult:
    return CareerFitResult(False, 0, "reject", evidence=evidence or [reason], rejection_reason=reason)


def evaluate(job: Job) -> CareerFitResult:
    cfg, terms = policy(), vocabulary()
    text = "\n".join([job.title, job.description or "", job.department or "", job.team or ""])
    if not job.active:
        return _reject("expired or inactive posting")
    if job.deadline:
        try:
            if date.fromisoformat(job.deadline[:10]) < date.today():
                return _reject("application deadline has passed")
        except ValueError:
            return _reject("unreadable application deadline requires review")
    blocked = hits(job.title, cfg["hard_reject_title_terms"])
    if blocked:
        return _reject("non-hardware career path", ["blocked title: " + blocked[0]])
    # Seniority only concerns the role title, never colleagues mentioned in the JD.
    senior = re.search(r"\b(senior|sr\.?|staff|principal|lead|manager|director|chief|supervisor)\b", job.title, re.I)
    if senior and not re.search(r"\blead\s+(acid|frame)\b", job.title, re.I):
        return _reject("inappropriate seniority", ["seniority title: " + senior.group()])
    if re.search(r"\bengineer\s+(iii|iv|v|[3-9])\b", job.title, re.I):
        return _reject("inappropriate seniority")
    from .smart_filters import assess_entry_level
    entry = assess_entry_level(job, config.filters().get("role", {}))
    if entry.rejection_reason and "requires" in entry.rejection_reason:
        return _reject(entry.rejection_reason)

    domain_hits = features(text)
    body_hits = features(job.description or "")
    core = sorted({v for values in domain_hits.values() for v in values})
    body_core = sorted({v for values in body_hits.values() for v in values})
    support = hits(text, terms["supporting_embedded"])
    software = hits(text, terms["software_dominance"])
    software_title = hits(job.title, terms["software_titles"])
    physical_title = hits(job.title, terms["hardware_titles"])
    # A hardware title and substantial physical work can contain incidental firmware.
    if software_title and (not physical_title or len(body_core) < 3):
        return _reject("firmware/software-focused role", ["software title: " + software_title[0]])
    if len(software) >= 3 and len(body_core) < 3:
        return _reject("software responsibilities dominate hardware evidence", software)
    if not core and not physical_title:
        return _reject("no physical electrical/hardware evidence")
    if not physical_title and len(core) < terms["minimum_hardware_hits"]:
        return _reject("generic title without substantial hardware evidence", core)

    w = cfg["weights"]
    hardware = min(w["hardware_skill"], 20 + len(core) * 4) if core else 25
    hands = hits(job.description or "", terms["hands_on"])
    growth = min(w["hands_on"], 8 + len(hands) * 4) if core else 8
    alignment = w["career_alignment"] if physical_title or len(core) >= 3 else 10
    entry_points = w["entry_level"] if entry.eligible or job.role_type == "new_grad" else 5
    company = w["company_fit"] if hits(job.company, cfg["preferred_companies"]) else 0
    location = w["location_fit"] if is_minnesota(job.location_str) else 0
    negative = hits(job.description or "", cfg["negative_description_terms"])
    penalty = min(24, len(negative) * 8)
    score = min(100, max(0, hardware + growth + alignment + entry_points + company + location - penalty))
    # Sparse feeds can be discovered, but the application policy requires a full JD.
    if physical_title and (not job.description or core):
        score = max(score, cfg["minimum_email_score"])
    band = next((b for b, cutoff in cfg["score_bands"].items() if score >= cutoff), "reject")
    evidence = ["hardware core: " + ", ".join(core)] if core else ["hardware title; full description needed"]
    if hands:
        evidence.append("hands-on work: " + ", ".join(hands))
    if support:
        evidence.append("supporting embedded (no independent points): " + ", ".join(support))
    if software:
        evidence.append("software terms considered in context: " + ", ".join(software))
    if location:
        evidence.append(f"Minnesota location +{location}")
    if company:
        evidence.append(f"configured hardware employer +{company}")
    if negative:
        evidence.append(f"non-target responsibilities -{penalty}: " + ", ".join(negative))
    evidence.extend(entry.evidence)
    passed = score >= cfg["minimum_email_score"]
    return CareerFitResult(passed, score, band, hardware, growth, alignment, company, location,
                           evidence, None if passed else "career fit below threshold", entry_points,
                           support, software, domain_hits)


def apply(job: Job) -> bool:
    result = evaluate(job)
    for attr, value in {
        "career_fit_score": result.score, "career_fit_band": result.band,
        "hardware_skill_score": result.hardware_skill, "resume_growth_score": result.resume_growth,
        "career_alignment_score": result.career_alignment, "company_quality_score": result.company_quality,
        "location_fit_score": result.location_fit, "career_fit_evidence": result.evidence,
    }.items():
        setattr(job, attr, value)
    job.priority = "A+" if result.score >= 95 else "A" if result.score >= 88 else "B" if result.score >= 75 else "C"
    job.hiring_signal = f"Hardware career fit {result.score}/100: {result.band.replace('_', ' ')}"
    if not result.passed:
        job.classification = "HARD_NO"
        job.decision_reasons = [result.rejection_reason or "rejected", *result.evidence]
    return result.passed
