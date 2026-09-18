"""Choose by verified hostname; metadata alone never authorizes personal-data upload."""
from .ashby import AshbyApplicator
from .greenhouse import GreenhouseApplicator
from .lever import LeverApplicator
from .staged import WorkdayAdapter, ICIMSAdapter, SmartRecruitersAdapter, GenericBrowserAdapter
from ..identity import detect_ats

_APPLICATORS = [GreenhouseApplicator(), LeverApplicator(), AshbyApplicator(),
                WorkdayAdapter(), ICIMSAdapter(), SmartRecruitersAdapter()]


def supported_ats():
    return {a.ats for a in _APPLICATORS}


def get_applicator(job):
    ats = detect_ats(job.application_url or job.url)
    return next((a for a in _APPLICATORS if a.ats == ats), GenericBrowserAdapter())
