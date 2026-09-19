"""Audited local execution: evaluate -> prepare -> recheck -> reserve -> submit."""
from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlsplit

from ..evaluation import evaluate
from ..models import ApplicantProfile, Job
from ..resumes import Resume
from ..identity import WORKDAY_MANUAL_REASON, is_workday_job
from . import applog, runner
from .base import FillOutcome
from .policy import Mode, decide, settings
from .registry import get_applicator
from .defense_gate import DEFENSE_MANUAL_REASON, is_defense_or_clearance_job


class ApplicationEngine:
    def __init__(self, profile: ApplicantProfile, resumes: list[Resume], mode=Mode.AUTO_SAFE):
        self.profile, self.resumes, self.mode = profile, resumes, mode

    def process(self, job: Job, page=None, *, reviewed=False, retry_failed=False, review_callback=None) -> str:
        # A single process owns the tracker through preparation and submission.
        # OS-backed lock is released on crashes; persisted 'submitting' still blocks retries.
        with applog.lock():
            state = applog.load()
            duplicate = applog.duplicate(job, state, retry_failed)
            if duplicate:
                if job.job_id in state:
                    from datetime import datetime, timezone
                    state[job.job_id].setdefault('duplicate_checks', []).append({
                        'ts': datetime.now(timezone.utc).isoformat(), 'reason': duplicate})
                else:
                    job.classification = 'HARD_NO'
                    job.decision_reasons = [duplicate]
                    applog.record(state, job, 'duplicate', duplicate)
                applog.save(state)
                return 'duplicate'   # Preserve the original confirmed/uncertain record.
            evaluate(job, self.resumes)
            if is_workday_job(job):
                # Discovery/scoring/resume matching are retained. No adapter, browser,
                # preparation or review callback is allowed beyond this boundary.
                status = 'rejected' if job.classification == 'HARD_NO' else 'needs_input'
                applog.record(state, job, status, WORKDAY_MANUAL_REASON)
                applog.save(state)
                return status
            if is_defense_or_clearance_job(job):
                # Keep these jobs in discovery/scoring, but never open/fill/submit
                # them through browser automation.
                applog.record(state, job, 'needs_input', DEFENSE_MANUAL_REASON)
                applog.save(state)
                return 'needs_input'
            adapter = get_applicator(job)
            job.application_url = adapter.application_url(job)
            job.ats = adapter.ats
            if job.classification == 'HARD_NO':
                applog.record(state, job, 'rejected', '; '.join(job.decision_reasons))
                applog.save(state)
                return 'rejected'
            if job.classification == 'HIGH_VALUE_REVIEW' and not reviewed and self.mode != Mode.PREPARE_ONLY:
                applog.record(state, job, 'high_value_review', 'customize and explicitly review this opportunity')
                applog.save(state)
                return 'high_value_review'
            if page is None or not getattr(adapter, 'automatic', True) or adapter.ats not in settings().get('allowed_auto_ats', []):
                applog.record(state, job, 'needs_input', 'manual ATS stage; open the recorded application link')
                applog.save(state)
                return 'needs_input'
            spec = next(r for r in self.resumes if r.id == job.selected_resume)
            if hashlib.sha256(Path(spec.path).read_bytes()).hexdigest() != spec.sha256:
                applog.record(state, job, 'needs_input', 'selected resume changed since review')
                applog.save(state)
                return 'needs_input'
            profile = self.profile.model_copy(update={'resume_path': spec.path})
            from .coverletter import generate_cover_letter
            cover = generate_cover_letter(job, profile)
            if cover:
                profile = profile.model_copy(update={'confirmed_answers': {**profile.confirmed_answers, 'Cover letter': cover}})
            outcome = runner.fill_application(page, job, adapter, profile)
            # PREPARE_ONLY must rehearse the final pre-submit inspection too.
            # A second inventory catches delayed iframes/widgets/conditional fields
            # that can appear after the initial fill.
            if self.mode == Mode.PREPARE_ONLY and not outcome.closed and not outcome.error:
                first = outcome
                outcome = runner.inspect_application(page, job, adapter, profile)
                if first.form_fingerprint and outcome.form_fingerprint and first.form_fingerprint != outcome.form_fingerprint:
                    outcome.blockers.append('form changed after initial preparation; manual inspection required')
            if reviewed or self.mode == Mode.REVIEW_ALL:
                reviewed = bool(review_callback and review_callback(job, outcome))
                # Re-inventory after the person has inspected the browser.
                outcome = runner.inspect_application(page, job, adapter, profile)
            decision = decide(job, outcome, self.mode, profile, reviewed=reviewed)
            if decision.may_submit:
                # Detect newly appearing questions, changed values and redirects immediately before click.
                fresh = runner.inspect_application(page, job, adapter, profile)
                decision = decide(job, fresh, self.mode, profile, reviewed=reviewed)
                if fresh.form_fingerprint != outcome.form_fingerprint:
                    decision.may_submit = False
                    decision.status, decision.reason = 'needs_input', 'form changed before submission'
                outcome = fresh
            if decision.may_submit and applog.daily_attempts(state) >= settings().get('daily_limit', 5):
                decision.may_submit = False
                decision.status, decision.reason = 'needs_input', 'daily submission-attempt limit reached'
            if not decision.may_submit:
                applog.record(state, job, decision.status, decision.reason,
                              unknown_questions=outcome.unknown_questions,
                              blockers=outcome.blockers, unfilled_required=outcome.unfilled_required)
                applog.save(state)
                return decision.status
            # Durable checkpoint BEFORE clicking. Never automatically retry ambiguous attempts.
            applog.record(state, job, 'submitting', decision.reason)
            applog.save(state)
            try:
                result = runner.submit(page, job=job)
            except Exception:
                result = runner.SubmissionResult('submission_unknown', 'unexpected interruption during submit; reconcile manually')
            applog.record(state, job, result.status, result.reason)
            applog.save(state)
            return result.status
