"""Orchestrator: collect -> filter -> dedup -> notify -> save state.

Usage:
    python -m src.main                 # full run (fetch, notify, persist state)
    python -m src.main --dry-run       # fetch + filter, print what WOULD send; no send, no save
    python -m src.main --test-notify   # send one sample email + SMS to verify credentials
    python -m src.main --no-sms        # run but skip SMS
    python -m src.main --limit 5       # cap sources (debugging)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from . import config
from .dedup import load_state, new_jobs, prune, save_state, update_state
from .filters import apply_filters
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
    for src in sources:
        all_jobs.extend(src.safe_fetch(session))
    log.info("collected %d raw jobs from %d sources", len(all_jobs), len(sources))
    return all_jobs


def _print_digest(jobs: list[Job]) -> None:
    order = config.settings().get("email", {}).get(
        "category_order", ["silicon", "hardware", "firmware", "other"]
    )
    grouped = email_notify.group_by_category(jobs, order)
    print("\n" + "=" * 70)
    print(f"  {len(jobs)} NEW matching internship(s)")
    print("=" * 70)
    for cat, group in grouped:
        label = email_notify._CATEGORY_LABELS.get(cat, cat)
        print(f"\n{label} ({len(group)})")
        for j in sorted(group, key=lambda x: (x.company.lower(), x.title.lower())):
            loc = j.location_str or "—"
            print(f"  • {j.title} — {j.company}  [{loc}]")
            print(f"      {j.url}")
    print()


def run_test_notify() -> int:
    secrets = config.secrets()
    settings = config.settings()
    sample = Job(
        company="Example Corp",
        title="Hardware Engineer Intern (Summer 2027)",
        url="https://example.com/jobs/hw-intern",
        locations=["New York, NY"],
        category="hardware",
        season="summer",
        year=2027,
    )
    sent_email = email_notify.send_email([sample], secrets, settings.get("email", {}))
    sms_cfg = settings.get("sms", {})
    sent_sms = False
    if sms_cfg.get("enabled", False):
        body = sms_notify.build_body(1, sms_cfg.get("template", "{n} new internships"))
        sent_sms = sms_notify.send_sms(f"[TEST] {body}", secrets)
    log.info("test-notify: email=%s sms=%s", sent_email, sent_sms)
    return 0 if (sent_email or sent_sms) else 1


def run(dry_run: bool, do_email: bool, do_sms: bool, limit: int | None, seed: bool = False) -> int:
    settings = config.settings()
    secrets = config.secrets()
    today = datetime.now().date()

    raw = collect_jobs(limit=limit)
    matched = apply_filters(raw)
    log.info("%d jobs passed filters", len(matched))

    state = load_state(config.state_path())

    if seed:
        # Mark everything currently open as already-seen, send nothing. Use this
        # once on first deploy so you only get *new* postings from then on.
        before = len(state)
        state = update_state(state, matched, today)
        state = prune(state, settings.get("prune_after_days", 120), today)
        save_state(config.state_path(), state)
        log.info("seeded %d jobs as seen (state %d -> %d); no notifications sent",
                 len(matched), before, len(state))
        return 0

    fresh = new_jobs(matched, state)
    log.info("%d are new (not previously seen)", len(fresh))

    if dry_run:
        _print_digest(fresh)
        log.info("dry-run: no notifications sent, state not modified")
        return 0

    suppress_empty = settings.get("suppress_when_empty", True)
    if not fresh and suppress_empty:
        log.info("no new jobs — nothing to send (suppress_when_empty=true)")
        # still persist pruned state so the file stays tidy
        state = prune(state, settings.get("prune_after_days", 120), today)
        save_state(config.state_path(), state)
        return 0

    if fresh:
        email_cfg = settings.get("email", {})
        sms_cfg = settings.get("sms", {})
        if do_email and email_cfg.get("enabled", True):
            email_notify.send_email(fresh, secrets, email_cfg)
        if do_sms and sms_cfg.get("enabled", True) and len(fresh) >= sms_cfg.get("min_jobs", 1):
            body = sms_notify.build_body(len(fresh), sms_cfg.get("template", "{n} new internships"))
            sms_notify.send_sms(body, secrets)

    # Persist: record the new jobs as seen, prune old entries.
    state = update_state(state, fresh, today)
    state = prune(state, settings.get("prune_after_days", 120), today)
    save_state(config.state_path(), state)
    log.info("state saved (%d total tracked jobs)", len(state))
    return 0


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    parser = argparse.ArgumentParser(description="Daily internship scraper + notifier")
    parser.add_argument("--dry-run", action="store_true", help="fetch+filter, print, do not send or save")
    parser.add_argument("--seed", action="store_true", help="mark all current matches as seen without sending (run once on first deploy)")
    parser.add_argument("--test-notify", action="store_true", help="send a sample email+SMS to verify creds")
    parser.add_argument("--no-email", action="store_true", help="skip email this run")
    parser.add_argument("--no-sms", action="store_true", help="skip SMS this run")
    parser.add_argument("--limit", type=int, default=None, help="cap number of sources (debug)")
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
