"""Browser mechanics; policy decisions live in ApplicationEngine."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
from . import fields
from .base import FillOutcome
from ..identity import detect_ats


def trusted_url(url: str) -> bool:
    p = urlsplit(url)
    return bool(p.scheme == 'https' and p.hostname and not p.username and not p.password and detect_ats(url))


def inspect_application(page, job, applicator, profile, *, fill=False) -> FillOutcome:
    outcome = FillOutcome(job=job, application_url=applicator.application_url(job))
    try:
        if not trusted_url(page.url) or detect_ats(page.url) != applicator.ats:
            outcome.blockers.append('unexpected application host or redirect; manual review required')
            return outcome
        if fields.looks_closed(page):
            outcome.closed = True
            return outcome
        audit = fields.audit_and_fill(page, profile, fill=fill)
        outcome.filled_fields = audit.filled
        outcome.resume_uploaded = audit.resume_uploaded
        outcome.unfilled_required = audit.required
        outcome.unknown_questions = audit.unknown
        outcome.blockers = audit.blockers
        outcome.inventory_complete = audit.complete
        outcome.form_fingerprint = audit.fingerprint
        outcome.submit_available = fields.find_submit_button(page) is not None
    except Exception as exc:
        outcome.error = 'form inspection failed: ' + type(exc).__name__
    return outcome


def fill_application(page, job, applicator, profile) -> FillOutcome:
    url = applicator.application_url(job)
    outcome = FillOutcome(job=job, application_url=url)
    if not trusted_url(url) or not getattr(applicator, 'automatic', True):
        outcome.blockers.append('adapter is review-only; use the application link manually')
        return outcome
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_selector('input,textarea,select', timeout=8000)
    except Exception as exc:
        outcome.error = 'navigation/form loading failed: ' + type(exc).__name__
        return outcome
    return inspect_application(page, job, applicator, profile, fill=True)


@dataclass
class SubmissionResult:
    status: str
    reason: str


def submit(page) -> SubmissionResult:
    """Success requires new, explicit confirmation, never merely a successful click."""
    try:
        btn = fields.find_submit_button(page)
        if btn is None:
            return SubmissionResult('failed', 'no unambiguous submit button; nothing clicked')
        confirmation = page.get_by_text(__import__('re').compile(
            r'application (?:has been )?(?:submitted|received)|received your application|thanks for applying|thank you for applying',
            __import__('re').I))
        before = confirmation.all_text_contents()
        btn.click(timeout=10000)
        page.wait_for_function(r'''before => {
            const body=document.body.innerText;
            const re=/application (?:has been )?(?:submitted|received)|received your application|thanks for applying|thank you for applying/ig;
            const hits=body.match(re)||[];
            return hits.some(hit=>!before.some(old=>old.toLowerCase().includes(hit.toLowerCase())));
        }''', arg=before, timeout=10000)
        return SubmissionResult('submitted', 'new explicit application confirmation observed')
    except Exception:
        return SubmissionResult('submission_unknown', 'submit attempt not confirmed; reconcile manually before any retry')
