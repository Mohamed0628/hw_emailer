"""Submission gates, independent of browser selectors or LLM output."""
from dataclasses import dataclass
from enum import Enum

from .. import config
from ..models import Job, ApplicantProfile
from .base import FillOutcome
from ..identity import WORKDAY_MANUAL_REASON, is_workday_job


class Mode(str, Enum):
    PREPARE_ONLY = "PREPARE_ONLY"
    REVIEW_ALL = "REVIEW_ALL"
    AUTO_SAFE = "AUTO_SAFE"
    AUTO_ELIGIBLE = "AUTO_ELIGIBLE"


ALIASES = {"auto_simple_review_hard": Mode.AUTO_SAFE, "review_all": Mode.REVIEW_ALL,
           "auto_all": Mode.AUTO_ELIGIBLE}


def parse_mode(value: str) -> Mode:
    return ALIASES[value] if value in ALIASES else Mode(value.upper())


def settings() -> dict:
    return config._load_yaml("application_policy.yaml")


@dataclass
class Decision:
    status: str
    reason: str
    may_submit: bool = False


def decide(job: Job, outcome: FillOutcome, mode: Mode, profile: ApplicantProfile,
           duplicate_reason: str | None = None, reviewed: bool = False) -> Decision:
    if is_workday_job(job):
        return Decision("needs_input", WORKDAY_MANUAL_REASON)
    if duplicate_reason:
        return Decision("duplicate", duplicate_reason)
    if job.classification == "HARD_NO":
        return Decision("rejected", "; ".join(job.decision_reasons))
    if job.classification not in {"AUTO_APPLY", "HIGH_VALUE_REVIEW"}:
        return Decision("needs_input", "job has not passed the shared evaluation pipeline")
    if outcome.closed:
        return Decision("expired", "posting closed")
    if outcome.error:
        return Decision("failed", outcome.error)
    if job.classification == "HIGH_VALUE_REVIEW" and not reviewed:
        return Decision("high_value_review", "customize this valuable opportunity and review explicitly")
    if mode == Mode.REVIEW_ALL and not reviewed:
        return Decision("needs_input", "review-all requires explicit review")
    if outcome.blockers or outcome.unknown_questions or outcome.unfilled_required:
        return Decision("needs_input", "; ".join(outcome.blockers + outcome.unknown_questions + outcome.unfilled_required))
    if not outcome.inventory_complete:
        return Decision("needs_input", "form inventory incomplete")
    if not outcome.resume_uploaded:
        return Decision("needs_input", "selected resume upload not verified")
    if not job.resume_match.get("confident") and not reviewed:
        return Decision("needs_input", "uncertain resume match; review the five-resume ranking")
    if settings().get("require_description", True) and not job.description:
        return Decision("needs_input", "full job description required")
    if settings().get("require_confirmed_start_date", True) and not profile.available_start_date:
        return Decision("needs_input", "exact available start date must be configured")
    if not outcome.submit_available:
        return Decision("needs_input", "unambiguous submit control not found")
    if mode == Mode.PREPARE_ONLY:
        return Decision("prepared", "all submission-readiness checks passed; prepare-only forbids submission")
    return Decision("auto_apply", "all candidate, resume, duplicate and form checks passed", True)
