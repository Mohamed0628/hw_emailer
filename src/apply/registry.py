"""Pick the right Applicator for a job."""

from __future__ import annotations

from ..models import Job
from .ashby import AshbyApplicator
from .base import Applicator
from .greenhouse import GreenhouseApplicator
from .lever import LeverApplicator

_APPLICATORS: list[Applicator] = [
    GreenhouseApplicator(),
    LeverApplicator(),
    AshbyApplicator(),
]


def supported_ats() -> set[str]:
    return {a.ats for a in _APPLICATORS}


def get_applicator(job: Job) -> Applicator | None:
    for a in _APPLICATORS:
        if a.can_handle(job):
            return a
    return None
