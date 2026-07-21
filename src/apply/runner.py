"""Fill (and optionally submit) a single application on an open page."""

from __future__ import annotations

import logging

from ..models import ApplicantProfile, Job
from . import fields
from .base import Applicator, FillOutcome

log = logging.getLogger(__name__)

_CONFIRM_MARKERS = (
    "thank you",
    "application submitted",
    "received your application",
    "thanks for applying",
    "we'll be in touch",
    "submitted successfully",
)


def fill_application(
    page,
    job: Job,
    applicator: Applicator,
    profile: ApplicantProfile,
) -> FillOutcome:
    """Navigate + fill the standard fields. Cover letter is added separately by
    the caller (only once a real form is confirmed) to avoid wasting API calls."""
    url = applicator.application_url(job)
    outcome = FillOutcome(job=job, application_url=url)
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
    except Exception as exc:  # noqa: BLE001
        outcome.error = f"navigation failed: {exc}"
        return outcome

    # Quick settle, then bail early if the posting is closed (no form to fill).
    try:
        page.wait_for_timeout(2000)
    except Exception:  # noqa: BLE001
        pass
    if fields.looks_closed(page):
        outcome.closed = True
        outcome.error = "posting closed / not accepting applications"
        return outcome

    # SPA forms (Ashby, new Greenhouse) render their inputs client-side and can
    # take several seconds — wait for an actual field to appear, not a fixed delay.
    try:
        page.wait_for_selector("input, textarea", timeout=8000)
    except Exception:  # noqa: BLE001
        pass
    # Nudge any lazy-rendered fields (custom questions) into the DOM, then settle.
    try:
        page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1200)
        page.mouse.wheel(0, -4000)
    except Exception:  # noqa: BLE001
        pass

    # Re-check after render — some SPAs paint the "closed" notice late.
    if fields.looks_closed(page):
        outcome.closed = True
        outcome.error = "posting closed / not accepting applications"
        return outcome

    outcome.filled_fields = fields.fill_text_fields(page, profile)
    if profile.resume_path:
        outcome.resume_uploaded = fields.upload_resume(page, profile.resume_path)

    outcome.unfilled_required = fields.find_unfilled_required(page)
    outcome.submit_available = fields.find_submit_button(page) is not None
    if not outcome.filled_fields and not outcome.submit_available:
        outcome.error = "no fillable application form found (posting may be closed or unsupported)"
    return outcome


def submit(page) -> tuple[bool, str]:
    """Click the submit button. Returns (clicked, note)."""
    btn = fields.find_submit_button(page)
    if btn is None:
        return False, "no submit button found"
    try:
        btn.click()
    except Exception as exc:  # noqa: BLE001
        return False, f"submit click failed: {exc}"
    try:
        page.wait_for_timeout(3500)
    except Exception:  # noqa: BLE001
        pass
    body = ""
    try:
        body = (page.inner_text("body") or "").lower()
    except Exception:  # noqa: BLE001
        pass
    if any(m in body for m in _CONFIRM_MARKERS):
        return True, "confirmation detected"
    return True, "clicked submit (no explicit confirmation text seen — verify)"
