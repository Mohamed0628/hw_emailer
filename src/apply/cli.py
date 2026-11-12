"""Local applications and an offline, side-effect-free evaluation mode."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from filelock import Timeout

from .. import config
from ..evaluation import evaluate_jobs
from ..alert_store import application_alert_jobs, load_alert_jobs
from ..main import collect_jobs
from ..models import Job
from ..resumes import load_resumes
from ..identity import is_workday_job
from ..application_targets import auto_apply_location_allowed, target_market
from . import applog, agent_browser
from .browser import BrowserSession
from .engine import ApplicationEngine
from .defense_gate import is_defense_or_clearance_job
from .registry import get_applicator
from .policy import Mode, parse_mode, settings
from .profile import load_profile


def _live_auto_candidates(jobs, retry_failed: bool, mode: Mode) -> list[Job]:
    """Return jobs that are worth spending a live browser slot on."""
    cfg = settings()
    allowed_ats = set(cfg.get("allowed_auto_ats", []))
    min_fit = int(cfg.get("minimum_resume_fit", 70))
    state = applog.load()
    market_order = {
        "Minnesota": 0,
        "California": 1,
        "Seattle/Washington": 2,
        "New York": 3,
    }

    candidates = []
    for job in jobs:
        allowed_classes = {"AUTO_APPLY"}
        if mode == Mode.AUTO_ELIGIBLE:
            allowed_classes.add("HIGH_VALUE_REVIEW")
        if job.classification not in allowed_classes:
            continue
        if (job.resume_fit_score or 0) < min_fit or not job.resume_match.get("confident"):
            continue
        if is_workday_job(job) or is_defense_or_clearance_job(job):
            continue
        if not auto_apply_location_allowed(job):
            continue
        adapter = get_applicator(job)
        if not getattr(adapter, "automatic", True) or adapter.ats not in allowed_ats:
            continue
        if applog.duplicate(job, state, retry_failed):
            continue
        candidates.append(job)

    return sorted(
        candidates,
        key=lambda job: (
            market_order.get(target_market(job) or "", 99),
            -(job.resume_fit_score or 0),
            -(job.career_fit_score or 0),
            job.company.casefold(),
            job.title.casefold(),
        ),
    )


def _review(job, outcome):
    print(json.dumps({'job_id': job.job_id, 'company': job.company, 'title': job.title,
                      'resume': job.selected_resume, 'match': job.resume_match,
                      'review': job.review_brief, 'unknown_questions': outcome.unknown_questions,
                      'blockers': outcome.blockers}, indent=2))
    try:
        return input('Inspect the browser and selected resume. Type this job ID to approve this application: ').strip() == job.job_id
    except EOFError:
        return False


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Local hardware applications; never run submission in CI')
    parser.add_argument('--profile', type=Path, help='private candidate YAML')
    source = parser.add_mutually_exclusive_group()
    source.add_argument('--jobs-json', type=Path, help='local array of normalized job postings (offline fixtures or saved jobs)')
    source.add_argument('--from-alerts', action='store_true',
                        help='use full normalized jobs persisted by hw_emailer alerts; legacy title-only history is excluded')
    parser.add_argument('--dry-run', action='store_true', help='evaluate only; no browser, notification, or tracker writes')
    parser.add_argument('--prepare-only', action='store_true', help='fill recognized forms; never click Submit')
    parser.add_argument('--mode', type=parse_mode, choices=list(Mode))
    parser.add_argument('--limit', type=int)
    parser.add_argument('--company')
    parser.add_argument('--category')
    parser.add_argument('--review-job', help='one job ID to open for explicit interactive review')
    parser.add_argument('--retry-failed', action='store_true', help='retry known failures; uncertain submissions remain blocked')
    parser.add_argument('--headless', action='store_true', help='allowed only with prepare-only')
    parser.add_argument('--no-cover-letter', action='store_true', help='compatibility flag; letters are never auto-generated')
    args = parser.parse_args(argv)
    cfg = settings()
    mode = Mode.PREPARE_ONLY if args.prepare_only else args.mode or parse_mode(cfg.get('mode', 'AUTO_SAFE'))
    if os.environ.get('CI') and not args.dry_run:
        parser.error('application browser execution is local-only')
    if args.headless and mode != Mode.PREPARE_ONLY:
        parser.error('headless is only allowed for PREPARE_ONLY')
    limit = args.limit if args.limit is not None else cfg.get('run_limit', 5)
    if limit < 1:
        parser.error('--limit must be positive')
    profile = load_profile(args.profile)
    if args.no_cover_letter:
        profile.approved_cover_letters = {}
    try:
        resumes = load_resumes(profile)
        if args.jobs_json:
            jobs = [Job(**j) for j in json.loads(args.jobs_json.read_text())]
        elif args.from_alerts:
            # Only full normalized alert records are eligible for the application
            # pipeline. Legacy seen_jobs history lacks descriptions and other
            # context needed for hardware scoring/resume selection, so merging it
            # here creates false 0-fit results and unsafe browser work.
            jobs = application_alert_jobs(load_alert_jobs(config.alert_jobs_path()))
            if not jobs:
                raise ValueError(
                    'No application-ready alert jobs found; run the notifier to populate full descriptions in data/alert_jobs.json'
                )
            # Alert records are the source of truth for navigation. They already
            # contain the exact URL discovered by hw_emailer, so application runs
            # must not reconstruct/verify every posting through an ATS API first.
            # The browser will detect a genuinely closed posting at that exact URL.
            if args.review_job:
                jobs = [j for j in jobs if j.job_id == args.review_job]
                if not jobs:
                    raise ValueError(f'Alert job not found: {args.review_job}')
        else:
            jobs = collect_jobs()
        evaluated = evaluate_jobs(jobs, resumes)
        if args.company:
            evaluated = [j for j in evaluated if args.company.casefold() in j.company.casefold()]
        if args.category:
            evaluated = [j for j in evaluated if j.category == args.category]
        if args.review_job and not args.from_alerts:
            evaluated = [j for j in evaluated if j.job_id == args.review_job]

        # Live automatic modes should spend --limit on genuinely auto-ready
        # candidates, not on Workday/defense/manual/rejected records.
        if mode in {Mode.AUTO_SAFE, Mode.AUTO_ELIGIBLE} and not args.review_job and not args.dry_run:
            evaluated = _live_auto_candidates(evaluated, args.retry_failed, mode)
            print(f"Live auto-ready queue: {len(evaluated)}")

        if args.dry_run:
            for j in evaluated[:limit]:
                print(json.dumps(j.model_dump(), ensure_ascii=False))
            return 0
        if not profile.full_name or not profile.email:
            raise ValueError('Full name and email are required in the candidate profile')
        engine = ApplicationEngine(profile, resumes, mode)
        agentic_execution = mode == Mode.AUTO_ELIGIBLE and agent_browser.enabled()
        if agentic_execution:
            print("Execution layer: browser-use agent")
        # AUTO_ELIGIBLE's agent owns its own browser session. The deterministic
        # Playwright browser remains available for PREPARE_ONLY/AUTO_SAFE/review.
        needs_browser = False if agentic_execution else any(
            not is_workday_job(j)
            and j.classification != 'HARD_NO'
            and getattr(get_applicator(j), 'automatic', True)
            and (
                j.classification != 'HIGH_VALUE_REVIEW'
                or args.review_job
                or mode in {Mode.PREPARE_ONLY, Mode.AUTO_ELIGIBLE}
            )
            for j in evaluated[:limit]
        )
        from contextlib import nullcontext
        session = BrowserSession(headless=args.headless) if needs_browser else nullcontext()
        counts = {}
        with session as browser:
            for job in evaluated[:limit]:
                status = engine.process(job, browser.page if browser else None,
                                        reviewed=bool(args.review_job), retry_failed=args.retry_failed,
                                        review_callback=_review if args.review_job or mode == Mode.REVIEW_ALL else None)
                counts[status] = counts.get(status, 0) + 1
                record = applog.load().get(job.job_id, {})
                print(json.dumps({
                    'job_id': job.job_id,
                    'company': job.company,
                    'status': status,
                    'reason': record.get('note') or record.get('review_reason') or record.get('failure_reason'),
                    'unknown_questions': record.get('unknown_questions') or [],
                    'blockers': record.get('blockers') or [],
                    'unfilled_required': record.get('unfilled_required') or [],
                }, ensure_ascii=False))
        print(json.dumps({'summary': counts}))
        return 0
    except (ValueError, OSError, KeyError, Timeout) as exc:
        print('Application run stopped: ' + str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
