"""Local auto-apply tool.

    python -m src.apply                 # apply per config (auto-simple / review-hard)
    python -m src.apply --prepare-only  # fill forms, NEVER submit (safe to try)
    python -m src.apply --limit 3       # cap how many this run
    python -m src.apply --headless      # no visible browser (testing only)
    python -m src.apply --company SpaceX --category hardware

Runs locally with a visible browser so you can watch, solve CAPTCHAs, and review
before submit. The daily email job is separate and unaffected.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .. import config
from ..filters import apply_filters
from ..main import collect_jobs
from . import applog as applog_mod
from . import fields
from . import runner
from .browser import BrowserSession
from .coverletter import generate_cover_letter
from .profile import load_profile
from .registry import get_applicator, supported_ats

log = logging.getLogger("intern_pos_emailer.apply")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _resolve_resume(profile) -> str:
    if not profile.resume_path:
        return ""
    p = Path(profile.resume_path)
    if not p.is_absolute():
        p = config.ROOT / p
    return str(p) if p.exists() else ""


def _candidate_jobs(args, applog, allowed_ats: set[str]):
    matched = apply_filters(collect_jobs())
    out = []
    seen_ids: set[str] = set()  # de-dup the same posting appearing in >1 list
    for job in matched:
        applicator = get_applicator(job)
        if not applicator or applicator.ats not in allowed_ats:
            continue
        if job.job_id in seen_ids:
            continue
        if applog_mod.is_done(job.job_id, applog, retry_failed=args.retry_failed):
            continue
        if args.category and (job.category or "") != args.category:
            continue
        if args.company and args.company.lower() not in job.company.lower():
            continue
        seen_ids.add(job.job_id)
        out.append(job)
    return out


def _review_prompt(outcome, cover: str | None = None) -> str:
    print("\n  --- REVIEW NEEDED ---")
    if outcome.unfilled_required:
        print("  Required fields still blank (complete them in the browser):")
        for f in outcome.unfilled_required[:15]:
            print(f"    - {f}")
    if cover and not outcome.cover_letter_filled:
        print("\n  Cover letter (no field auto-detected — copy/paste if the form wants one):")
        print("  " + "-" * 60)
        for line in cover.splitlines():
            print("  | " + line)
        print("  " + "-" * 60)
    print("  Check the form in the browser window.")
    try:
        ans = input("  [Enter]=submit  s=skip  q=quit: ").strip().lower()
    except EOFError:
        return "skip"
    if ans == "q":
        return "quit"
    if ans == "s":
        return "skip"
    return "submit"


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(description="Local auto-apply tool")
    parser.add_argument("--limit", type=int, default=None, help="max applications this run")
    parser.add_argument("--prepare-only", action="store_true", help="fill forms but never submit")
    parser.add_argument("--headless", action="store_true", help="no visible browser (testing)")
    parser.add_argument("--no-cover-letter", action="store_true", help="don't generate cover letters")
    parser.add_argument("--category", choices=["silicon", "hardware", "firmware"], help="only this category")
    parser.add_argument("--company", help="only companies whose name contains this")
    parser.add_argument("--mode", choices=["auto_simple_review_hard", "review_all", "auto_all"])
    parser.add_argument("--retry-failed", action="store_true", help="re-attempt jobs previously marked failed")
    args = parser.parse_args(argv)

    settings = config.settings()
    acfg = settings.get("apply", {})
    mode = args.mode or acfg.get("mode", "auto_simple_review_hard")
    limit = args.limit if args.limit is not None else acfg.get("daily_limit", 10)
    gen_cover = acfg.get("generate_cover_letter", True) and not args.no_cover_letter
    allowed_ats = set(acfg.get("supported_ats", list(supported_ats()))) & supported_ats()

    # 1) Profile.
    profile = load_profile()
    profile.resume_path = _resolve_resume(profile)
    if not profile.is_configured:
        print(
            "\nProfile not ready. Create config/profile.yaml (copy "
            "config/profile.example.yaml) and set at least full_name, email, and "
            "resume_path (a real file under resumes/). Then re-run.\n"
        )
        return 1

    # 2) Candidate jobs.
    applog = applog_mod.load()
    jobs = _candidate_jobs(args, applog, allowed_ats)
    if not jobs:
        log.info("no new applicable jobs (supported ATS, not already applied)")
        return 0
    jobs = jobs[:limit]
    log.info("will process %d job(s) in mode=%s prepare_only=%s", len(jobs), mode, args.prepare_only)

    # 3) Drive the browser.
    counts = {"submitted": 0, "reviewed": 0, "skipped": 0, "failed": 0, "prepared": 0, "closed": 0}
    with BrowserSession(headless=args.headless) as bs:
        for i, job in enumerate(jobs, 1):
            # Stop cleanly if the browser window was closed (don't churn the rest).
            try:
                if bs.page.is_closed():
                    print("\nBrowser was closed — stopping. Re-run to continue (progress is saved).")
                    break
            except Exception:  # noqa: BLE001
                print("\nBrowser is unavailable — stopping.")
                break

            # Skip if it became done earlier in THIS run (e.g. a duplicate).
            if applog_mod.is_done(job.job_id, applog, retry_failed=args.retry_failed):
                continue

            applicator = get_applicator(job)
            print(f"\n[{i}/{len(jobs)}] {job.title} — {job.company} ({applicator.ats})")

            outcome = runner.fill_application(bs.page, job, applicator, profile)
            print(f"  form: {outcome.application_url}")
            print(
                f"  filled={outcome.filled_fields} resume={outcome.resume_uploaded} "
                f"unfilled_required={len(outcome.unfilled_required)} "
                f"submit_btn={outcome.submit_available}"
            )

            if outcome.error and "has been closed" in outcome.error.lower():
                print("\nBrowser was closed — stopping. Re-run to continue (progress is saved).")
                break

            if outcome.closed:
                print("  SKIP: posting is closed / not accepting applications")
                counts["closed"] += 1
                applog_mod.record(applog, job, "closed", "not accepting applications")
                applog_mod.save(applog)
                continue

            if outcome.error:
                print(f"  ERROR: {outcome.error}")
                counts["failed"] += 1
                applog_mod.record(applog, job, "failed", outcome.error)
                applog_mod.save(applog)
                continue

            # Real, fillable form confirmed — only NOW spend an API call on the
            # cover letter (closed/failed jobs above cost nothing).
            cover = generate_cover_letter(job, profile) if gen_cover else None
            if cover:
                outcome.cover_letter_filled = fields.fill_cover_letter(bs.page, cover)
                print("  cover letter: " + (
                    "generated + filled" if outcome.cover_letter_filled
                    else "generated (paste at review)"
                ))

            if args.prepare_only:
                counts["prepared"] += 1
                applog_mod.record(applog, job, "prepared", "prepare-only")
                applog_mod.save(applog)
                continue

            # Decide: submit, review, or skip.
            auto = (
                mode == "auto_all"
                or (mode == "auto_simple_review_hard" and outcome.is_simple)
            ) and outcome.submit_available

            if auto:
                ok, note = runner.submit(bs.page)
                status = "submitted" if ok else "failed"
                counts[status] += 1
                print(f"  auto-submitted: {note}")
                applog_mod.record(applog, job, status, note)
            else:
                action = _review_prompt(outcome, cover)
                if action == "quit":
                    applog_mod.save(applog)
                    break
                if action == "skip":
                    counts["skipped"] += 1
                    applog_mod.record(applog, job, "skipped", "user skipped")
                else:
                    ok, note = runner.submit(bs.page)
                    # You reviewed and chose to submit — mark it DONE either way.
                    # If the auto-click missed the button, you likely submitted in
                    # the browser yourself; either way we never re-show this job.
                    counts["submitted" if ok else "reviewed"] += 1
                    print(f"  {'submitted' if ok else 'reviewed (you handle submit in browser)'}: {note}")
                    applog_mod.record(applog, job, "submitted" if ok else "reviewed", f"reviewed; {note}")
            applog_mod.save(applog)

    print(
        f"\nDone. submitted={counts['submitted']} skipped={counts['skipped']} "
        f"closed={counts['closed']} failed={counts['failed']} prepared={counts['prepared']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
