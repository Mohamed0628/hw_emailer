"""Persisted state: which jobs have already been notified.

State file shape (data/seen_jobs.json):
    { "<job_id>": {"first_seen": "2026-06-22", "company": ..., "title": ..., "url": ...}, ... }
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from .models import Job
from .identity import strong_keys, prefer_direct
from .apply.applog import _atomic_text

log = logging.getLogger(__name__)


def load_state(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid seen-job state; restore it before notifying")
    return data


def save_state(path: Path, state: dict[str, dict]) -> None:
    _atomic_text(path, json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def new_jobs(jobs: list[Job], state: dict[str, dict]) -> list[Job]:
    """Jobs whose id is not already in state (deduped within the batch too)."""
    known = {"legacy:" + jid for jid in state}
    for entry in state.values():
        if entry.get("url"):
            old = Job(company=entry.get("company", ""), title=entry.get("title", ""), url=entry["url"],
                      requisition_id=entry.get("requisition_id"))
            known.update(strong_keys(old))
    out = []
    for job in prefer_direct(jobs):
        keys = strong_keys(job)
        if keys & known:
            continue
        known.update(keys)
        out.append(job)
    return out


def update_state(
    state: dict[str, dict], jobs: list[Job], today: date | None = None
) -> dict[str, dict]:
    today = today or datetime.now().date()
    iso = today.isoformat()
    for job in jobs:
        state[job.job_id] = {
            "first_seen": iso,
            "company": job.company,
            "title": job.title,
            "url": job.url,
            "requisition_id": job.requisition_id,
        }
    return state


def prune(
    state: dict[str, dict], max_age_days: int, today: date | None = None
) -> dict[str, dict]:
    if not max_age_days or max_age_days <= 0:
        return state
    today = today or datetime.now().date()
    cutoff = today - timedelta(days=max_age_days)
    kept: dict[str, dict] = {}
    for jid, meta in state.items():
        fs = meta.get("first_seen")
        try:
            seen_date = date.fromisoformat(fs) if fs else today
        except ValueError:
            seen_date = today
        if seen_date >= cutoff:
            kept[jid] = meta
    removed = len(state) - len(kept)
    if removed:
        log.info("pruned %d stale state entries (> %d days)", removed, max_age_days)
    return kept
