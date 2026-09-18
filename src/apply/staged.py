"""Explicit manual stages for ATSs without validated native form support."""
from .base import Applicator
from ..identity import detect_ats


class ManualAdapter(Applicator):
    automatic = False

    def can_handle(self, job):
        return detect_ats(job.url) == self.ats

    def application_url(self, job):
        return job.application_url or job.url


class WorkdayAdapter(ManualAdapter):
    ats = 'workday'


class ICIMSAdapter(ManualAdapter):
    ats = 'icims'


class SmartRecruitersAdapter(ManualAdapter):
    ats = 'smartrecruiters'


class GenericBrowserAdapter(ManualAdapter):
    ats = 'generic'

    def can_handle(self, job):
        return True
