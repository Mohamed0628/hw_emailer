"""Recover full job context from legacy seen_jobs history without applying.

This is a one-time/backfill tool for jobs alerted before data/alert_jobs.json stored
full normalized postings. It revisits the exact historical URL, reads the live page,
and promotes still-live postings with usable text into the full alert store.

It never fills or submits application forms.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from src import config
from src.alert_store import jobs_from_seen_state, load_alert_jobs, merge_alert_jobs, save_alert_jobs
from src.apply.browser import BrowserSession
from src.apply.fields import text_looks_closed
from src.dedup import load_state
from src.identity import detect_ats, strong_keys

REPORT_PATH = config.ROOT / "data" / "legacy_recovery_report.json"


def _parse_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None


def _valid_url(url: str) -> bool:
    p = urlsplit(url)
    return bool(p.scheme in {"http", "https"} and p.hostname and not p.username and not p.password)


def _missing_legacy_jobs(since_days: int | None) -> list:
    seen = load_state(config.state_path())
    legacy = jobs_from_seen_state(seen)
    stored = load_alert_jobs(config.alert_jobs_path())

    stored_keys = {key for job in stored for key in strong_keys(job)}
    cutoff = date.today() - timedelta(days=since_days) if since_days else None

    out = []
    for job in legacy:
        if any(key in stored_keys for key in strong_keys(job)):
            continue
        meta = seen.get(job.job_id, {})
        # seen_jobs may be keyed by an older identity; fall back to a metadata lookup.
        if not meta:
            meta = next(
                (
                    value for value in seen.values()
                    if value.get("company") == job.company
                    and value.get("title") == job.title
                    and value.get("url") == job.url
                ),
                {},
            )
        first_seen = _parse_day(meta.get("first_seen"))
        if cutoff and first_seen and first_seen < cutoff:
            continue
        if _valid_url(job.url):
            out.append(job)
    return out


def _extract_text(page) -> str:
    # Prefer semantic job-content containers when available, then fall back to body.
    selectors = [
        "main",
        '[class*="job-description"]',
        '[class*="jobDescription"]',
        '[data-qa*="job-description"]',
        "body",
    ]
    candidates: list[str] = []
    for selector in selectors:
        try:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 3)):
                if loc.nth(i).is_visible():
                    text = loc.nth(i).inner_text().strip()
                    if text:
                        candidates.append(text)
        except Exception:
            continue
    return max(candidates, key=len, default="")


def _save_report(rows: list[dict]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Recover full context for legacy alerted jobs; never applies."
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=120,
        help="recover legacy jobs first seen within this many days; 0 means all history",
    )
    parser.add_argument("--limit", type=int, help="optional cap for a partial recovery pass")
    parser.add_argument("--headless", action="store_true", help="run recovery browser headless")
    parser.add_argument("--delay", type=float, default=0.25, help="seconds between page loads")
    args = parser.parse_args(argv)

    since_days = args.since_days or None
    jobs = _missing_legacy_jobs(since_days)
    if args.limit:
        jobs = jobs[: args.limit]

    existing = load_alert_jobs(config.alert_jobs_path())
    recovered = []
    report: list[dict] = []
    counts: Counter[str] = Counter()

    print(f"Legacy jobs queued for recovery: {len(jobs)}")
    if not jobs:
        print("Nothing to recover.")
        return 0

    with BrowserSession(headless=args.headless) as browser:
        page = browser.page
        for index, job in enumerate(jobs, 1):
            status = "failed"
            detail = ""
            try:
                page.goto(job.url, wait_until="domcontentloaded", timeout=30000)
                body = _extract_text(page)
                if text_looks_closed(body):
                    status = "closed"
                    detail = "posting appears closed"
                elif len(body) < 200:
                    status = "insufficient"
                    detail = "live page did not expose enough posting text"
                else:
                    ats = detect_ats(page.url) or detect_ats(job.url)
                    recovered_job = job.model_copy(
                        update={
                            "url": job.url,
                            "description": body,
                            "source": "legacy-recovered" + (f":{ats}" if ats else ""),
                            "ats": ats or job.ats,
                            "active": True,
                        }
                    )
                    recovered.append(recovered_job)
                    existing = merge_alert_jobs(existing, [recovered_job])
                    status = "recovered"
                    detail = f"{len(body)} characters"
            except Exception as exc:
                status = "failed"
                detail = type(exc).__name__

            counts[status] += 1
            report.append(
                {
                    "job_id": job.job_id,
                    "company": job.company,
                    "title": job.title,
                    "url": job.url,
                    "status": status,
                    "detail": detail,
                }
            )

            if recovered and (len(recovered) % 10 == 0 or index == len(jobs)):
                save_alert_jobs(config.alert_jobs_path(), existing)
            if index % 25 == 0 or index == len(jobs):
                print(
                    f"  checked {index}/{len(jobs)} | "
                    + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
                )
                _save_report(report)
            if args.delay:
                time.sleep(max(args.delay, 0.0))

    if recovered:
        save_alert_jobs(config.alert_jobs_path(), existing)
    _save_report(report)

    print("\nRecovery summary:", dict(counts))
    print(f"Recovered postings promoted to: {config.alert_jobs_path()}")
    print(f"Detailed report: {REPORT_PATH}")
    print("No application forms were filled or submitted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
