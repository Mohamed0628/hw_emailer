"""Concurrent source collection for faster scraper runs."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import config
from .models import Job
from .sources.base import make_session

log = logging.getLogger(__name__)


def _fetch_one(source) -> tuple[str, list[Job], float]:
    started = time.perf_counter()
    session = make_session()
    try:
        jobs = source.safe_fetch(session)
    finally:
        session.close()
    return source.name, jobs, time.perf_counter() - started


def collect_sources(sources: list) -> list[Job]:
    runtime = config.settings().get("runtime", {}) or {}
    workers = max(1, int(runtime.get("source_workers", 24)))
    slow_limit = float(runtime.get("slow_source_seconds", 8))
    started = time.perf_counter()
    jobs: list[Job] = []
    slow: list[tuple[float, str]] = []

    log.info("fetching %d sources with %d workers", len(sources), workers)
    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(sources)))) as pool:
        futures = {pool.submit(_fetch_one, source): source.name for source in sources}
        for future in as_completed(futures):
            name = futures[future]
            try:
                _, source_jobs, elapsed = future.result()
            except Exception as exc:  # noqa: BLE001
                log.warning("source %s failed in worker: %s", name, exc)
                continue
            jobs.extend(source_jobs)
            if elapsed >= slow_limit:
                slow.append((elapsed, name))

    elapsed = time.perf_counter() - started
    log.info("collected %d raw jobs from %d sources in %.1fs", len(jobs), len(sources), elapsed)
    if slow:
        slow.sort(reverse=True)
        log.warning(
            "slowest sources: %s",
            ", ".join(f"{name}={seconds:.1f}s" for seconds, name in slow[:10]),
        )
    return jobs
