"""Local applications and an offline, side-effect-free evaluation mode."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from filelock import Timeout

from .. import config
from ..evaluation import evaluate_jobs
from ..alert_store import jobs_from_seen_state, load_alert_jobs, merge_alert_jobs
from ..dedup import load_state
from ..main import collect_jobs
from ..models import Job
from ..resumes import load_resumes
from ..identity import is_workday_job
from . import applog
from .browser import BrowserSession
from .engine import ApplicationEngine
from .policy import Mode, parse_mode, settings
from .profile import load_profile


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
                        help='use jobs previously surfaced by hw_emailer; includes legacy seen-state backfill')
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
            stored = load_alert_jobs(config.alert_jobs_path())
            legacy = jobs_from_seen_state(load_state(config.state_path()))
            jobs = merge_alert_jobs(legacy, stored)
            if not jobs:
                raise ValueError('No prior alert jobs found; run the notifier first')
        else:
            jobs = collect_jobs()
        evaluated = evaluate_jobs(jobs, resumes)
        if args.company:
            evaluated = [j for j in evaluated if args.company.casefold() in j.company.casefold()]
        if args.category:
            evaluated = [j for j in evaluated if j.category == args.category]
        if args.review_job:
            evaluated = [j for j in evaluated if j.job_id == args.review_job]
        if args.dry_run:
            for j in evaluated[:limit]:
                print(json.dumps(j.model_dump(), ensure_ascii=False))
            return 0
        if not profile.full_name or not profile.email:
            raise ValueError('Full name and email are required in the candidate profile')
        engine = ApplicationEngine(profile, resumes, mode)
        # Only open a browser if at least one supported job actually needs it.
        from .registry import get_applicator
        needs_browser = any(not is_workday_job(j) and j.classification != 'HARD_NO' and getattr(get_applicator(j), 'automatic', True)
                            and (j.classification != 'HIGH_VALUE_REVIEW' or args.review_job or mode == Mode.PREPARE_ONLY)
                            for j in evaluated[:limit])
        from contextlib import nullcontext
        session = BrowserSession(headless=args.headless) if needs_browser else nullcontext()
        counts = {}
        with session as browser:
            for job in evaluated[:limit]:
                status = engine.process(job, browser.page if browser else None,
                                        reviewed=bool(args.review_job), retry_failed=args.retry_failed,
                                        review_callback=_review if args.review_job or mode == Mode.REVIEW_ALL else None)
                counts[status] = counts.get(status, 0) + 1
                print(json.dumps({'job_id': job.job_id, 'company': job.company, 'status': status}))
        print(json.dumps({'summary': counts}))
        return 0
    except (ValueError, OSError, KeyError, Timeout) as exc:
        print('Application run stopped: ' + str(exc))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
