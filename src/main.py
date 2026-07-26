"""Orchestrator: collect -> filter -> dedup -> notify -> save state."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from . import config
from .consumer_2027_filters import apply_filters
from .dedup import load_state, new_jobs, prune, save_state, update_state
from .models import Job
from .notify import email as email_notify
from .notify import sms as sms_notify
from .sources.base import make_session
from .sources.registry import build_all_sources

log = logging.getLogger("intern_pos_emailer")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def collect_jobs(limit: int | None = None) -> list[Job]:
    sources = build_all_sources()
    if limit:
        sources = sources[:limit]
    session = make_session()
    all_jobs: list[Job] = []
    for source in sources:
        all_jobs.extend(source.safe_fetch(session))
    log.info("collected %d raw jobs from %d sources", len(all_jobs), len(sources))
    return all_jobs


def _print_digest(jobs: list[Job]) -> None:
    order = config.settings().get("email", {}).get(
        "category_order", ["silicon", "hardware", "firmware", "other"]
    )
    grouped = email_notify.group_by_category(jobs, order)
    print("\n" + "=" * 70)
    print(f"  {len(jobs)} NEW matching opportunity(s)")
    print("=" * 70)
    for category, group in grouped:
        label = email_notify._CATEGORY_LABELS.get(category, category)
        print(f"\n{label} ({len(group)})")
        for job in sorted(group, key=lambda x: (x.company.lower(), x.title.lower())):
            location = job.location_str or "-"
            role = (job.role_type or "opportunity").replace("_", " ")
            priority = f"Priority {job.priority} | " if job.priority else ""
            print(f"  {priority}{job.title} - {job.company} [{location}] [{role}]")
            if job.hiring_signal:
                print(f"      {job.hiring_signal}")
            print(f"      {job.url}")
    print()


def run_test_notify() -> int:
    secrets = config.secrets()
    settings = config.settings()
    sample = Job(
        company="Example Corp",
        title="Hardware Engineer I",
        url="https://example.com/jobs/hardware-engineer-i",
        locations=["Minneapolis, MN"],
        category="hardware",
        role_type="new_grad",
        priority="A",
        hiring_signal="Minnesota medtech target",
        entry_level_score=8,
        entry_level_evidence=["Engineer I title"],
    )
    sent_email = email_notify.send_email([sample], secrets, settings.get("email", {}))
    sms_cfg = settings.get("sms", {})
    sent_sms = False
    if sms_cfg.get("enabled", False):
        body = sms_notify.build_body(1, sms_cfg.get("template", "{n} new opportunities"))
        sent_sms = sms_notify.send_sms(f"[TEST] {body}", secrets)
    log.info("test-notify: email=%s sms=%s", sent_email, sent_sms)
    return 0 if (sent_email or sent_sms) else 1


def run(
    dry_run: bool,
    do_email: bool,
    do_sms: bool,
    limit: int | None,
    seed: bool = False,
) -> int:
    settings = config.settings()
    secrets = config.secrets()
    today = datetime.now().date()

    raw = collect_jobs(limit=limit)
    matched = apply_filters(raw)
    log.info("%d jobs passed filters", len(matched))

    state = load_state(config.state_path())

    if seed:
        before = len(state)
        state = update_state(state, matched, today)
        state = prune(state, settings.get("prune_after_days", 120), today)
        save_state(config.state_path(), state)
        log.info(
            "seeded %d jobs as seen (state %d -> %d); no notifications sent",
            len(matched),
            before,
            len(state),
        )
        return 0

    fresh = new_jobs(matched, state)
    log.info("%d are new (not previously seen)", len(fresh))

    if dry_run:
        _print_digest(fresh)
        log.info("dry-run: no notifications sent, state not modified")
        return 0

    suppress_empty = settings.get("suppress_when_empty", True)
    if not fresh and suppress_empty:
        log.info("no new jobs - nothing to send (suppress_when_empty=true)")
        state = prune(state, settings.get("prune_after_days", 120), today)
        save_state(config.state_path(), state)
        return 0

    if fresh:
        email_cfg = settings.get("email", {})
        sms_cfg = settings.get("sms", {})
        if do_email and email_cfg.get("enabled", True):
            email_notify.send_email(fresh, secrets, email_cfg)
        if (
            do_sms
            and sms_cfg.get("enabled", True)
            and len(fresh) >= sms_cfg.get("min_jobs", 1)
        ):
            body = sms_notify.build_body(
                len(fresh),
                sms_cfg.get("template", "{n} new opportunities"),
            )
            sms_notify.send_sms(body, secrets)

    state = update_state(state, fresh, today)
    state = prune(state, settings.get("prune_after_days", 120), today)
    save_state(config.state_path(), state)
    log.info("state saved (%d total tracked jobs)", len(state))
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(
        description="Hardware internship and early-career job scraper"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and filter, print results, do not send or save",
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="mark all current matches as seen without sending",
    )
    parser.add_argument(
        "--test-notify",
        action="store_true",
        help="send a sample email and SMS to verify credentials",
    )
    parser.add_argument("--no-email", action="store_true", help="skip email this run")
    parser.add_argument("--no-sms", action="store_true", help="skip SMS this run")
    parser.add_argument("--limit", type=int, default=None, help="cap number of sources")
    args = parser.parse_args(argv)

    if args.test_notify:
        return run_test_notify()
    return run(
        dry_run=args.dry_run,
        do_email=not args.no_email,
        do_sms=not args.no_sms,
        limit=args.limit,
        seed=args.seed,
    )


if __name__ == "__main__":
    sys.exit(main())
