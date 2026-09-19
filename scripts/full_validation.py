"""One-command validation for the guarded application pipeline.

Runs syntax checks, the full pytest suite (including browser fixtures), then audits
all stored alert jobs in PREPARE_ONLY. This script never permits submission.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)


def run_stream(label: str, cmd: list[str], env: dict[str, str] | None = None) -> tuple[int, list[dict]]:
    print(f"\n{'=' * 20} {label} {'=' * 20}", flush=True)
    proc = subprocess.Popen(
        cmd,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    parsed: list[dict] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line, end="", flush=True)
        try:
            item = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(item, dict) and item.get("job_id"):
            parsed.append(item)
    return proc.wait(), parsed


def alert_count() -> int:
    try:
        from src import config
        from src.alert_store import jobs_from_seen_state, load_alert_jobs, merge_alert_jobs
        from src.dedup import load_state

        stored = load_alert_jobs(config.alert_jobs_path())
        legacy = jobs_from_seen_state(load_state(config.state_path()))
        return len(merge_alert_jobs(legacy, stored))
    except Exception as exc:
        print(f"Could not count alerts ahead of time: {exc}")
        return 10000


def summarize_audit(rows: list[dict]) -> None:
    print(f"\n{'=' * 20} AUDIT SUMMARY {'=' * 20}")
    if not rows:
        print("No per-job audit rows were produced.")
        return

    statuses = Counter(row.get("status", "unknown") for row in rows)
    print("Statuses:", dict(statuses))

    try:
        from src.apply import applog

        state = applog.load()
    except Exception as exc:
        print(f"Could not load application state for reasons: {exc}")
        return

    reasons: Counter[str] = Counter()
    details: list[tuple[str, str, str, str]] = []
    for row in rows:
        jid = row.get("job_id", "")
        record = state.get(jid, {})
        reason = (
            record.get("note")
            or record.get("review_reason")
            or record.get("failure_reason")
            or "no recorded reason"
        )
        reasons[reason] += 1
        blockers = "; ".join(record.get("blockers") or [])
        match = record.get("resume_match") or {}
        confidence = match.get("confident")
        fit = record.get("resume_fit_score")
        resume_info = f"resume_fit={fit}, confident={confidence}"
        if blockers:
            resume_info += f", blockers={blockers}"
        details.append((str(row.get("company", "")), str(jid), str(row.get("status", "")), f"{reason} [{resume_info}]"))

    print("\nGrouped reasons:")
    for reason, count in reasons.most_common():
        print(f"  {count:>3}  {reason}")

    print("\nPer-job results:")
    for company, jid, status, detail in details:
        print(f"  {status:<14} {company:<28} {jid}  {detail}")


def main() -> int:
    failures: list[str] = []

    rc, _ = run_stream(
        "SYNTAX",
        [sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"],
    )
    if rc:
        failures.append("syntax")

    test_env = os.environ.copy()
    test_env["REQUIRE_BROWSER_TESTS"] = "1"
    rc, _ = run_stream(
        "FULL PYTEST",
        [sys.executable, "-m", "pytest", "-q"],
        env=test_env,
    )
    if rc:
        failures.append("pytest")

    total = alert_count()
    print(f"\nStored alert jobs to audit: {total}")
    rc, rows = run_stream(
        "ALL ALERTS PREPARE_ONLY",
        [
            sys.executable,
            "-m",
            "src.apply",
            "--from-alerts",
            "--prepare-only",
            "--limit",
            str(max(total, 1)),
        ],
    )
    if rc:
        failures.append("alert-audit")

    summarize_audit(rows)

    print(f"\n{'=' * 20} FINAL {'=' * 20}")
    if failures:
        print("Validation completed with failing phases:", ", ".join(failures))
        return 1
    print("Validation completed. No syntax/test harness failures. PREPARE_ONLY audit never submits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
