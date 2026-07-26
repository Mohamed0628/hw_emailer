"""Temporarily validate the final robotics and consumer-hardware ATS catalog."""

from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "companies_robotics_consumer_hardware.yaml"
TIMEOUT = 15


def validate_greenhouse(entry: dict) -> tuple[str, bool, str]:
    company = str(entry["company"])
    token = str(entry["token"])
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    try:
        response = requests.get(url, timeout=TIMEOUT)
        if response.status_code != 200:
            return company, False, f"Greenhouse HTTP {response.status_code}"
        payload = response.json()
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list) or not jobs:
            return company, False, "Greenhouse board has no listed jobs"
        return company, True, f"Greenhouse OK, {len(jobs)} jobs"
    except Exception as exc:  # noqa: BLE001
        return company, False, f"Greenhouse error: {exc}"


def validate_lever(entry: dict) -> tuple[str, bool, str]:
    company = str(entry["company"])
    token = str(entry["token"])
    url = f"https://api.lever.co/v0/postings/{token}"
    try:
        response = requests.get(url, params={"mode": "json"}, timeout=TIMEOUT)
        if response.status_code != 200:
            return company, False, f"Lever HTTP {response.status_code}"
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            return company, False, "Lever board has no listed jobs"
        return company, True, f"Lever OK, {len(payload)} jobs"
    except Exception as exc:  # noqa: BLE001
        return company, False, f"Lever error: {exc}"


def validate_ashby(entry: dict) -> tuple[str, bool, str]:
    company = str(entry["company"])
    token = str(entry["token"])
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    try:
        response = requests.get(url, timeout=TIMEOUT)
        if response.status_code != 200:
            return company, False, f"Ashby HTTP {response.status_code}"
        payload = response.json()
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        listed = [job for job in jobs or [] if job.get("isListed") is not False]
        if not listed:
            return company, False, "Ashby board has no listed jobs"
        return company, True, f"Ashby OK, {len(listed)} jobs"
    except Exception as exc:  # noqa: BLE001
        return company, False, f"Ashby error: {exc}"


def main() -> int:
    with CATALOG.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}

    validators = {
        "greenhouse": validate_greenhouse,
        "lever": validate_lever,
        "ashby": validate_ashby,
    }
    tasks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        for source, validator in validators.items():
            for entry in payload.get(source, []):
                tasks.append(executor.submit(validator, entry))
        results = [future.result() for future in tasks]

    failed = False
    for company, ok, detail in sorted(results):
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {company}: {detail}")
        failed = failed or not ok

    print(f"Validated {len(results)} configured company boards")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
