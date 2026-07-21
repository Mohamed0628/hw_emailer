"""Greenhouse applicator: the job URL is the application form page."""

from __future__ import annotations

from ..models import Job
from .base import Applicator


class GreenhouseApplicator(Applicator):
    ats = "greenhouse"

    def can_handle(self, job: Job) -> bool:
        return job.ats == "greenhouse" or "greenhouse.io" in (job.url or "")

    def application_url(self, job: Job) -> str:
        # Greenhouse renders the application form inline on the job page.
        return job.url
