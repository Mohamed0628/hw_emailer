"""Applicator abstraction + per-ATS registry.

Most of the form-filling is generic (see fields.py). An Applicator's job is the
ATS-specific bits: recognizing a job and deriving its application-form URL.
`submit()` stays unimplemented at this layer on purpose — submission is driven
by the runner/CLI so it can honor the user's review-vs-auto mode and log every
attempt.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from ..models import Job


@dataclass
class FillOutcome:
    """Result of filling an application form (no submission decision here)."""

    job: Job
    application_url: str
    filled_fields: list[str] = field(default_factory=list)
    resume_uploaded: bool = False
    cover_letter_filled: bool = False
    unfilled_required: list[str] = field(default_factory=list)
    submit_available: bool = False
    closed: bool = False  # posting no longer accepting applications
    error: str = ""

    @property
    def is_simple(self) -> bool:
        """No leftover required fields → safe to auto-submit."""
        return not self.unfilled_required and not self.error


class Applicator(ABC):
    ats: str = "base"

    @abstractmethod
    def can_handle(self, job: Job) -> bool:
        ...

    @abstractmethod
    def application_url(self, job: Job) -> str:
        """The URL of the fillable application form for this job."""

    def submit(self, *args, **kwargs):
        raise NotImplementedError(
            "Submission is handled by the runner/CLI so it can honor "
            "review-vs-auto mode and log every attempt."
        )
