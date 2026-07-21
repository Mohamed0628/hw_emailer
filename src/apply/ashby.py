"""Ashby applicator: the application form lives at <jobUrl>/application."""

from __future__ import annotations

from ..models import Job
from .base import Applicator


class AshbyApplicator(Applicator):
    ats = "ashby"

    def can_handle(self, job: Job) -> bool:
        return job.ats == "ashby" or "jobs.ashbyhq.com" in (job.url or "")

    def application_url(self, job: Job) -> str:
        base = (job.url or "").rstrip("/")
        return base if base.endswith("/application") else f"{base}/application"
