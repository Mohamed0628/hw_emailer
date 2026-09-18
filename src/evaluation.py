"""One decision pipeline for email, offline reports, and browser applications."""
from __future__ import annotations

from . import career_fit, config
from .consumer_2027_filters import passes
from .identity import prefer_direct
from .models import Job
from .resumes import Resume, annotate
from .signals import features, is_minnesota, vocabulary
from .smart_filters import explain_pass


def evaluate(job: Job, resumes: list[Resume] | None = None) -> Job:
    job.classification = None
    job.review_brief = {}
    from urllib.parse import urlsplit
    parsed_url = urlsplit(job.url)
    if parsed_url.scheme not in {"https", "http"} or not parsed_url.hostname or parsed_url.username:
        job.classification = "HARD_NO"
        job.decision_reasons = ["invalid or suspicious application URL"]
        return job
    career = career_fit.evaluate(job)
    if not career.passed or not passes(job):
        career_fit.apply(job)
        job.classification = "HARD_NO"
        job.decision_reasons = [career.rejection_reason or explain_pass(job).get("rejection_reason") or "ineligible cohort/location/role"]
        return job
    match = annotate(job, resumes) if resumes else None
    domains = features(job.title + "\n" + (job.description or ""))
    valuable = [d for d in vocabulary()["high_value_domains"] if len(domains[d]) >= 3]
    medtech = is_minnesota(job.location_str) and (job.category == "medtech_hardware" or len(domains["medtech_hardware"]) >= 2)
    dream = job.company.casefold() in {c.casefold() for c in vocabulary().get("dream_companies", [])}
    high_value = bool(valuable or medtech or dream) and job.career_fit_score >= career_fit.policy()["high_value_score"]
    job.classification = "HIGH_VALUE_REVIEW" if high_value else "AUTO_APPLY"
    job.decision_reasons = ["valuable technical opportunity; customize before applying" if high_value else
                            "eligible hardware role; form and candidate checks still required", *job.career_fit_evidence]
    if high_value:
        job.review_brief = {
            "why": job.decision_reasons,
            "best_resume": job.selected_resume or "local resume catalog required",
            "suggested_resume_changes": ["Reorder existing project bullets to emphasize " + ", ".join(match.evidence[:6])
                                         if match else "Compare the five local resumes before editing"],
            "important_keywords": match.evidence if match else sorted({t for ts in domains.values() for t in ts}),
            "unverified_keywords_do_not_claim": match.missing_terms if match else [],
            "networking_opportunity": "Contact not yet researched; identify an engineering/recruiting contact on the company website",
            "outreach_recommendation": "Request a brief conversation about this team's hardware work; no message sent",
            "deadline": job.deadline or "unknown",
        }
    return job


def evaluate_jobs(jobs: list[Job], resumes: list[Resume] | None = None) -> list[Job]:
    result = [evaluate(job, resumes) for job in prefer_direct(jobs)]
    return sorted(result, key=lambda j: (j.classification == "HARD_NO", j.role_type != "new_grad", -j.career_fit_score))


def apply_filters(jobs: list[Job]) -> list[Job]:
    return [job for job in evaluate_jobs(jobs) if job.classification != "HARD_NO"]
