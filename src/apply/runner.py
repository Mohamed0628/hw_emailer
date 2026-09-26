"""Browser mechanics; policy decisions live in ApplicationEngine."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit
from . import fields
from .base import FillOutcome
from ..identity import detect_ats, requisition, canonical_url, is_workday_job, WORKDAY_MANUAL_REASON


def trusted_url(url: str) -> bool:
    p = urlsplit(url)
    return bool(p.scheme == 'https' and p.hostname and not p.username and not p.password and detect_ats(url))


def inspect_application(page, job, applicator, profile, *, fill=False) -> FillOutcome:
    if is_workday_job(job):
        return FillOutcome(job=job, application_url=job.application_url or job.url,
                           blockers=[WORKDAY_MANUAL_REASON])
    outcome = FillOutcome(job=job, application_url=applicator.application_url(job))
    try:
        if not trusted_url(page.url) or detect_ats(page.url) != applicator.ats:
            outcome.blockers.append('unexpected application host or redirect; manual review required')
            return outcome
        expected = applicator.application_url(job)
        actual_job = job.model_copy(update={'url': page.url, 'application_url': None, 'requisition_id': None})
        expected_job = job.model_copy(update={'url': expected, 'application_url': None, 'requisition_id': None})
        # Same ATS is not enough, but application views often rewrite the URL and
        # omit the requisition id. Reject a conflicting explicit requisition; when
        # the redirected URL has no id, accept only if the rendered page still
        # identifies the same posting by title (and company when present).
        expected_id, actual_id = requisition(expected_job), requisition(actual_job)
        if expected_id and actual_id and actual_id != expected_id:
            outcome.blockers.append('application redirected to a different requisition')
            return outcome
        if expected_id and not actual_id:
            body = page.inner_text('body')[:8000]
            body_norm = ' '.join(body.casefold().split())
            title_norm = ' '.join(job.title.casefold().split())
            company_norm = ' '.join(job.company.casefold().split())
            id_in_page = expected_id.casefold() in page.content().casefold()
            title_in_page = bool(title_norm and title_norm in body_norm)
            company_in_page = bool(company_norm and company_norm in body_norm)
            if not id_in_page and not (title_in_page and company_in_page):
                outcome.blockers.append('application redirected to an unverifiable requisition')
                return outcome
        if not expected_id and canonical_url(expected) != canonical_url(page.url):
            body = page.inner_text('body')[:8000]
            body_norm = ' '.join(body.casefold().split())
            title_norm = ' '.join(job.title.casefold().split())
            company_norm = ' '.join(job.company.casefold().split())
            if not (title_norm in body_norm and company_norm in body_norm):
                outcome.blockers.append('application redirected to an unverifiable requisition')
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
    if is_workday_job(job):
        return FillOutcome(job=job, application_url=job.application_url or job.url,
                           blockers=[WORKDAY_MANUAL_REASON])
    url = applicator.application_url(job)
    outcome = FillOutcome(job=job, application_url=url)
    if not trusted_url(url) or not getattr(applicator, 'automatic', True):
        outcome.blockers.append('adapter is review-only; use the application link manually')
        return outcome
    try:
        page.goto(url, wait_until='domcontentloaded', timeout=30000)
    except Exception as exc:
        # Some ATS pages finish rendering useful DOM after the navigation
        # deadline. If we are still on the trusted target ATS, inspect what
        # actually loaded before classifying the job as a hard failure.
        if trusted_url(page.url) and detect_ats(page.url) == applicator.ats:
            inspected = inspect_application(page, job, applicator, profile, fill=True)
            if inspected.closed or inspected.inventory_complete or inspected.blockers:
                return inspected
        outcome.error = 'navigation/form loading failed: ' + type(exc).__name__
        return outcome

    if fields.looks_closed(page):
        outcome.closed = True
        return outcome

    try:
        page.wait_for_selector(
            'input,textarea,select,[role="combobox"],[role="checkbox"],[role="radiogroup"]',
            timeout=12000,
        )
    except Exception:
        # Let the normal inventory explain the page (closed, custom/manual,
        # no controls, redirect) instead of turning every selector timeout into
        # a generic navigation failure.
        return inspect_application(page, job, applicator, profile, fill=True)
    return inspect_application(page, job, applicator, profile, fill=True)


@dataclass
class SubmissionResult:
    status: str
    reason: str


def submit(page, *, job=None) -> SubmissionResult:
    """Success requires new, explicit confirmation, never merely a successful click."""
    try:
        if (job is not None and is_workday_job(job)) or detect_ats(page.url) == 'workday':
            return SubmissionResult('needs_input', WORKDAY_MANUAL_REASON)
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
