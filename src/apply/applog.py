"""Persistent record of application attempts.

Written to two files, kept in sync on every save:
  - data/applications.json  (machine state, keyed by job_id — used for dedup)
  - data/applications.csv   (human-friendly tracker, open in Excel/Sheets)

Shape: { "<job_id>": {"status", "ts", "company", "title", "url", "ats", "note"} }
status: submitted | reviewed | skipped | failed | closed | prepared
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path

from .. import config
from ..models import Job

log = logging.getLogger(__name__)

APPLOG_PATH = config.ROOT / "data" / "applications.json"
APPLOG_CSV = config.ROOT / "data" / "applications.csv"

CSV_COLUMNS = ["date", "company", "title", "status", "ats", "url", "note"]

# Statuses that mean "don't try this job again" — terminal, never retried.
_TERMINAL = {"submitted", "reviewed", "skipped", "closed"}
# "failed" is also skipped by default (so you don't re-see the same dead /
# embedded / expired forms every run); `--retry-failed` re-attempts these.
_RETRYABLE = {"failed"}


def load() -> dict[str, dict]:
    if not APPLOG_PATH.exists():
        return {}
    try:
        with APPLOG_PATH.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("could not read applications log: %s", exc)
        return {}


def write_csv(applog: dict[str, dict]) -> None:
    """Mirror the applog to a human-friendly CSV (newest first)."""
    APPLOG_CSV.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(applog.values(), key=lambda r: r.get("ts", ""), reverse=True)
    with APPLOG_CSV.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    "date": (r.get("ts") or "")[:10],
                    "company": r.get("company", ""),
                    "title": r.get("title", ""),
                    "status": r.get("status", ""),
                    "ats": r.get("ats", ""),
                    "url": r.get("url", ""),
                    "note": r.get("note", ""),
                }
            )


def save(applog: dict[str, dict]) -> None:
    APPLOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with APPLOG_PATH.open("w", encoding="utf-8") as fh:
        json.dump(applog, fh, indent=2, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    write_csv(applog)  # keep the CSV tracker in sync


def is_done(job_id: str, applog: dict[str, dict], retry_failed: bool = False) -> bool:
    """True if we've already handled this job and shouldn't process it again.

    By default a `failed` entry also counts as done (avoids re-showing the same
    dead/expired forms). Pass retry_failed=True to re-attempt failed ones.
    """
    status = applog.get(job_id, {}).get("status")
    if status in _TERMINAL:
        return True
    if status in _RETRYABLE:
        return not retry_failed
    return False


def record(applog: dict[str, dict], job: Job, status: str, note: str = "") -> None:
    applog[job.job_id] = {
        "status": status,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "company": job.company,
        "title": job.title,
        "url": job.url,
        "ats": job.ats,
        "note": note,
    }
