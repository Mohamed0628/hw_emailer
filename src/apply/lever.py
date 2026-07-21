"""Lever applicator: the application form lives at <jobUrl>/apply."""

from __future__ import annotations

from ..models import Job
from .base import Applicator


class LeverApplicator(Applicator):
    ats = "lever"

    def can_handle(self, job: Job) -> bool:
        return job.ats == "lever" or "jobs.lever.co" in (job.url or "")

    def application_url(self, job: Job) -> str:
        base = (job.url or "").rstrip("/")
        return base if base.endswith("/apply") else f"{base}/apply"
