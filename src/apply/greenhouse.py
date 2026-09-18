"""Greenhouse applicator: the job URL is the application form page."""

from __future__ import annotations

from ..models import Job
from ..identity import detect_ats
from .base import Applicator


class GreenhouseApplicator(Applicator):
    ats = "greenhouse"

    def can_handle(self, job: Job) -> bool:
        return detect_ats(job.url) == self.ats

    def application_url(self, job: Job) -> str:
        # Greenhouse renders the application form inline on the job page.
        return job.application_url or job.url
