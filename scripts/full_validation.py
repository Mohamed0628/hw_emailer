"""One-command validation for the guarded application pipeline.

Default mode runs syntax checks, the full pytest suite (including browser
fixtures), then audits every stored alert job in PREPARE_ONLY. It never submits.
Use --summary-only to summarize the most recent/partial audit without browsing.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AUDIT_ROWS_PATH = ROOT / "data" / "last_validation_rows.jsonl"


def _append_audit_row(row: dict) -> None:
    AUDIT_ROWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_ROWS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_saved_rows() -> list[dict]:
    if not AUDIT_ROWS_PATH.exists():
        return []
    rows: list[dict] = []
    for line in AUDIT_ROWS_PATH.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict) and item.get("job_id"):
            rows.append(item)
    return rows


def run_stream(
    label: str,
    cmd: list[str],
    env: dict[str, str] | None = None,
    *,
    echo: bool = True,
    save_audit_rows: bool = False,
) -> tuple[int, list[dict]]:
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
    live_counts: Counter[str] = Counter()
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            if echo:
                print(line, end="", flush=True)
            try:
                item = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(item, dict) or not item.get("job_id"):
                continue
            parsed.append(item)
            live_counts[str(item.get("status", "unknown"))] += 1
            if save_audit_rows:
                _append_audit_row(item)
                if len(parsed) % 25 == 0:
                    print(
                        f"  audited {len(parsed)} jobs | "
                        + ", ".join(f"{k}={v}" for k, v in sorted(live_counts.items())),
                        flush=True,
                    )
    except KeyboardInterrupt:
        print("\nAudit interrupted; partial rows were saved and can be summarized with --summary-only.", flush=True)
        proc.terminate()
        proc.wait()
        return 130, parsed
    return proc.wait(), parsed


def alert_jobs():
    from src import config
    from src.alert_store import load_alert_jobs

    # Validate the same queue the application runner uses: full normalized
    # alert records only. Legacy seen-state history is intentionally excluded.
    return load_alert_jobs(config.alert_jobs_path())


def alert_count() -> int:
    return len(alert_jobs())


def rows_from_current_state() -> list[dict]:
    from src.apply import applog

    state = applog.load()
    rows: list[dict] = []
    for job in alert_jobs():
        record = state.get(job.job_id)
        if record:
            rows.append(
                {
                    "job_id": job.job_id,
                    "company": job.company,
                    "status": record.get("status", "unknown"),
                }
            )
    return rows


def summarize_audit(rows: list[dict]) -> None:
    print(f"\n{'=' * 20} AUDIT SUMMARY {'=' * 20}")
    if not rows:
        print("No audit rows are available yet.")
        return

    # Keep the last result for a job if a partial file contains repeated runs.
    latest = {str(row.get("job_id")): row for row in rows if row.get("job_id")}
    rows = list(latest.values())

    statuses = Counter(str(row.get("status", "unknown")) for row in rows)
    print(f"Jobs summarized: {len(rows)}")
    print("Statuses:", dict(statuses))

    from src.apply import applog

    state = applog.load()
    reasons: Counter[str] = Counter()
    blocker_counts: Counter[str] = Counter()
    fit_counts: Counter[str] = Counter()
    details: list[tuple[str, str, str, str]] = []

    for row in rows:
        jid = str(row.get("job_id", ""))
        record = state.get(jid, {})
        reason = (
            record.get("note")
            or record.get("review_reason")
            or record.get("failure_reason")
            or "no recorded reason"
        )
        reasons[str(reason)] += 1

        blockers = record.get("blockers") or []
        for blocker in blockers:
            blocker_counts[str(blocker)] += 1

        match = record.get("resume_match") or {}
        confident = match.get("confident")
        fit = record.get("resume_fit_score")
        if confident is False:
            fit_counts["resume match not confident"] += 1
        if fit == 0:
            fit_counts["resume fit = 0"] += 1

        info = f"resume_fit={fit}, confident={confident}"
        if blockers:
            info += ", blockers=" + "; ".join(str(x) for x in blockers)
        details.append(
            (
                str(row.get("company", "")),
                jid,
                str(row.get("status", "")),
                f"{reason} [{info}]",
            )
        )

    print("\nGrouped reasons:")
    for reason, count in reasons.most_common():
        print(f"  {count:>3}  {reason}")

    if blocker_counts:
        print("\nBlockers:")
        for blocker, count in blocker_counts.most_common():
            print(f"  {count:>3}  {blocker}")

    if fit_counts:
        print("\nResume diagnostics:")
        for reason, count in fit_counts.most_common():
            print(f"  {count:>3}  {reason}")

    print("\nFailed jobs:")
    failed = [d for d in details if d[2] == "failed"]
    if failed:
        for company, jid, status, detail in failed:
            print(f"  {status:<12} {company:<28} {jid}  {detail}")
    else:
        print("  none")

    print("\nPrepared jobs:")
    prepared = [d for d in details if d[2] == "prepared"]
    if prepared:
        for company, jid, status, detail in prepared:
            print(f"  {status:<12} {company:<28} {jid}  {detail}")
    else:
        print("  none")

    print("\nUse applications.json for the complete per-job record; summary output is intentionally compact.")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="summarize saved/current application state without tests or browser navigation",
    )
    args = parser.parse_args()

    if args.summary_only:
        rows = _load_saved_rows()
        if not rows:
            rows = rows_from_current_state()
        summarize_audit(rows)
        return 0

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

    AUDIT_ROWS_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_ROWS_PATH.write_text("", encoding="utf-8")
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
        echo=False,
        save_audit_rows=True,
    )
    if rc:
        failures.append("alert-audit")

    summarize_audit(rows or _load_saved_rows())

    print(f"\n{'=' * 20} FINAL {'=' * 20}")
    if failures:
        print("Validation completed with failing phases:", ", ".join(failures))
        print("Run: python scripts/full_validation.py --summary-only")
        return 1
    print("Validation completed. PREPARE_ONLY audit never submits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
