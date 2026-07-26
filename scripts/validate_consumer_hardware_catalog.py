#!/usr/bin/env python3
"""Temporary live validation for the final additional consumer-hardware catalog."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path
from typing import Any

import requests
import yaml

CATALOG = Path("config/companies_consumer_hardware_more.yaml")
TIMEOUT = 15
ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=false",
    "lever": "https://api.lever.co/v0/postings/{token}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{token}",
}


def _rows(source: str, payload: Any) -> list[Any]:
    if source == "lever":
        return payload if isinstance(payload, list) else []
    if isinstance(payload, dict):
        rows = payload.get("jobs") or []
        return rows if isinstance(rows, list) else []
    return []


def _probe(source: str, company: str, token: str) -> tuple[str, bool, str]:
    url = ENDPOINTS[source].format(token=token)
    try:
        response = requests.get(
            url,
            timeout=TIMEOUT,
            headers={"User-Agent": "hw-emailer-board-validator/1.0"},
        )
        if response.status_code != 200:
            return company, False, f"HTTP {response.status_code}: {url}"
        rows = _rows(source, response.json())
        if not rows:
            return company, False, f"zero jobs: {url}"
        return company, True, f"{source}:{token} ({len(rows)} jobs)"
    except (requests.RequestException, ValueError, TypeError) as error:
        return company, False, f"{type(error).__name__}: {url}"


def main() -> int:
    payload = yaml.safe_load(CATALOG.read_text(encoding="utf-8")) or {}
    entries = [
        (source, str(entry["company"]), str(entry["token"]))
        for source in ENDPOINTS
        for entry in payload.get(source, []) or []
    ]

    results: list[tuple[str, bool, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        futures = [pool.submit(_probe, *entry) for entry in entries]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    failures = []
    for company, passed, detail in sorted(results, key=lambda item: item[0].casefold()):
        print(f"[{'PASS' if passed else 'FAIL'}] {company}: {detail}")
        if not passed:
            failures.append(company)

    print(f"Validated {len(results) - len(failures)}/{len(results)} boards")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
