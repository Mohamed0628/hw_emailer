"""Atomic, backwards-compatible application state and conservative duplicate checks."""
from __future__ import annotations

import csv
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from filelock import FileLock

from .. import config
from ..identity import canonical_url, possible_key, requisition, strong_keys
from ..models import Job

APPLOG_PATH = config.ROOT / "data" / "applications.json"
APPLOG_CSV = config.ROOT / "data" / "applications.csv"
CSV_COLUMNS = ["date", "company", "title", "location", "job_id", "requisition_id", "status", "ats", "url",
               "application_url", "date_discovered", "date_applied", "classification", "career_fit_score",
               "resume_used", "resume_fit_score", "failure_reason", "review_reason", "unknown_questions",
               "networking_priority", "source", "application_restriction", "note"]
_TERMINAL = {"submitted", "reviewed", "skipped", "closed", "expired", "submitting", "submission_unknown"}


def lock() -> FileLock:
    APPLOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(APPLOG_PATH) + ".lock", timeout=0)


def load() -> dict[str, dict]:
    if not APPLOG_PATH.exists():
        return {}
    # Corrupt/unreadable state must stop applications, not erase duplicate history.
    data = json.loads(APPLOG_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or any(not isinstance(v, dict) for v in data.values()):
        raise ValueError("Invalid application state; restore a backup before continuing")
    return data


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def write_csv(applog: dict[str, dict]) -> None:
    import io
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for record in sorted(applog.values(), key=lambda r: r.get("ts", ""), reverse=True):
        row = dict(record, date=(record.get("ts") or "")[:10])
        for key, value in row.items():
            if isinstance(value, (dict, list)):
                row[key] = json.dumps(value, ensure_ascii=False)
            elif isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                row[key] = "'" + value  # CSV formula injection protection
        writer.writerow(row)
    _atomic_text(APPLOG_CSV, buffer.getvalue())


def save(applog: dict[str, dict]) -> None:
    if APPLOG_PATH.exists():
        # Keep original legacy state before the first schema upgrade, byte for byte.
        backup = APPLOG_PATH.with_suffix(".legacy.bak")
        existing = load()
        if existing and not backup.exists() and any(r.get("schema_version", 1) < 2 for r in existing.values()):
            _atomic_text(backup, APPLOG_PATH.read_text())
    _atomic_text(APPLOG_PATH, json.dumps(applog, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    write_csv(applog)


def is_done(job_id: str, applog: dict[str, dict], retry_failed: bool = False) -> bool:
    status = applog.get(job_id, {}).get("status")
    return status in _TERMINAL or (status == "failed" and not retry_failed)


def duplicate(job: Job, applog: dict[str, dict], retry_failed: bool = False) -> str | None:
    keys = strong_keys(job)
    for old_id, record in applog.items():
        if not is_done(old_id, applog, retry_failed):
            continue
        old = Job(company=record.get("company", ""), title=record.get("title", record.get("job_title", "")),
                  url=record.get("url", record.get("canonical_job_url", "")),
                  locations=record.get("locations") or ([record["location"]] if record.get("location") else []),
                  ats=record.get("ats"), requisition_id=record.get("requisition_id"),
                  application_url=record.get("application_url"))
        if old_id == job.job_id or keys & strong_keys(old):
            return "same requisition already handled: " + str(record.get("status"))
        # Distinct explicit requisitions are allowed even when their titles match.
        if requisition(job) and requisition(old) and requisition(job) != requisition(old):
            continue
        if possible_key(job) == possible_key(old):
            return "possible duplicate company/title/location; reconcile manually"
        if not old.locations and job.company.casefold() == old.company.casefold() and job.title.casefold() == old.title.casefold():
            return "possible legacy duplicate without location; reconcile manually"
    return None


def daily_attempts(applog: dict[str, dict]) -> int:
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(1 for r in applog.values() for event in r.get("attempts", [])
               if event.get("status") == "submitting" and event.get("ts", "").startswith(today))


def record(applog: dict[str, dict], job: Job, status: str, note: str = "", **extra) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    old = applog.get(job.job_id, {})
    if old.get("status") == "submitted":
        return  # Never downgrade a confirmed submission or record it twice.
    row = dict(old)
    row.update({
        "schema_version": 2, "status": status, "submission_status": status, "ts": now,
        "company": job.company, "title": job.title, "job_title": job.title,
        "location": job.location_str, "locations": job.locations, "job_id": job.job_id,
        "requisition_id": requisition(job), "url": job.url, "canonical_job_url": canonical_url(job.url),
        "application_url": job.application_url or job.url, "ats": job.ats,
        "date_discovered": old.get("date_discovered", now),
        "date_applied": now if status == "submitted" else old.get("date_applied"),
        "classification": job.classification, "career_fit_score": job.career_fit_score,
        "application_restriction": job.application_restriction,
        "resume_used": job.selected_resume, "resume_fit_score": job.resume_fit_score,
        "resume_match": job.resume_match, "decision_reasons": job.decision_reasons,
        "failure_reason": note if status in {"failed", "submission_unknown"} else None,
        "review_reason": note if status in {"needs_input", "high_value_review", "prepared"} else None,
        "unknown_questions": [], "networking_priority": "high" if job.classification == "HIGH_VALUE_REVIEW" else "normal",
        "review_brief": job.review_brief, "source": job.source, "note": note,
    })
    row.update(extra)
    row["attempts"] = [*old.get("attempts", []), {"ts": now, "status": status, "reason": note}]
    applog[job.job_id] = row
