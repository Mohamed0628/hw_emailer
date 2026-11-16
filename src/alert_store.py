"""Persistent normalized jobs surfaced by the notifier.

This is the handoff between discovery/email and the local application runner.
It intentionally stores normalized Job objects, not email text, so application
runs never need to rediscover every configured company.
"""
from __future__ import annotations

import json
from pathlib import Path

from .identity import prefer_direct, strong_keys
from .models import Job
from .application_targets import enrich_missing_target_location


def load_alert_jobs(path: Path) -> list[Job]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Invalid alert-job store; expected a JSON array")
    return [Job(**item) for item in payload]


def save_alert_jobs(path: Path, jobs: list[Job]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps([j.model_dump() for j in prefer_direct(jobs)],
                   indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def merge_alert_jobs(existing: list[Job], new: list[Job]) -> list[Job]:
    """Merge without losing richer/newer normalized records."""
    merged: list[Job] = list(existing)
    known: dict[str, int] = {}
    for idx, job in enumerate(merged):
        for key in strong_keys(job):
            known[key] = idx

    for job in new:
        matches = {known[key] for key in strong_keys(job) if key in known}
        if matches:
            idx = min(matches)
            old = merged[idx]
            # Prefer the new record when it carries at least as much useful
            # application context; preserve Workday provenance via prefer_direct.
            old_dump = old.model_dump()
            new_dump = job.model_dump()
            if bool(job.description) or not old.description:
                old_dump.update({k: v for k, v in new_dump.items()
                                 if v not in (None, "", [], {})})
                merged[idx] = Job(**old_dump)
            for key in strong_keys(merged[idx]):
                known[key] = idx
            continue
        idx = len(merged)
        merged.append(job)
        for key in strong_keys(job):
            known[key] = idx
    return prefer_direct(merged)


def jobs_from_seen_state(state: dict[str, dict]) -> list[Job]:
    """Best-effort backfill for alerts sent before the full store existed."""
    out = []
    for meta in state.values():
        if meta.get("company") and meta.get("title") and meta.get("url"):
            out.append(Job(
                company=meta["company"],
                title=meta["title"],
                url=meta["url"],
                requisition_id=meta.get("requisition_id"),
                source="alert-history",
            ))
    return prefer_direct(out)


def application_alert_jobs(jobs: list[Job]) -> list[Job]:
    """Return alert records with enough context for guarded application work.

    Legacy seen-state backfills and descriptionless records stay available for
    history/email purposes, but must not enter resume selection or browser
    automation.
    """
    eligible = [
        enrich_missing_target_location(job)
        for job in jobs
        if job.source != "alert-history" and bool((job.description or "").strip())
    ]
    return prefer_direct(eligible)
