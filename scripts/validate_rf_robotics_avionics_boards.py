"""Temporarily validate the final 30 public ATS feeds during PR review."""

from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "companies_rf_robotics_avionics.yaml"
TIMEOUT = 20


def validate_greenhouse(entry: dict) -> tuple[str, bool, str]:
    company = str(entry["company"])
    token = str(entry["token"])
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    try:
        response = requests.get(url, timeout=TIMEOUT)
        payload = response.json() if response.status_code == 200 else {}
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if response.status_code == 200 and isinstance(jobs, list):
            return company, True, f"greenhouse:{token}, jobs={len(jobs)}"
        return company, False, f"greenhouse:{token}, HTTP {response.status_code}"
    except Exception as exc:  # noqa: BLE001
        return company, False, f"greenhouse:{token}, {exc}"


def validate_lever(entry: dict) -> tuple[str, bool, str]:
    company = str(entry["company"])
    token = str(entry["token"])
    url = f"https://api.lever.co/v0/postings/{token}"
    try:
        response = requests.get(url, params={"mode": "json"}, timeout=TIMEOUT)
        payload = response.json() if response.status_code == 200 else None
        if response.status_code == 200 and isinstance(payload, list):
            return company, True, f"lever:{token}, jobs={len(payload)}"
        return company, False, f"lever:{token}, HTTP {response.status_code}"
    except Exception as exc:  # noqa: BLE001
        return company, False, f"lever:{token}, {exc}"


def validate_ashby(entry: dict) -> tuple[str, bool, str]:
    company = str(entry["company"])
    token = str(entry["token"])
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    try:
        response = requests.get(url, timeout=TIMEOUT)
        payload = response.json() if response.status_code == 200 else {}
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if response.status_code == 200 and isinstance(jobs, list):
            return company, True, f"ashby:{token}, jobs={len(jobs)}"
        return company, False, f"ashby:{token}, HTTP {response.status_code}"
    except Exception as exc:  # noqa: BLE001
        return company, False, f"ashby:{token}, {exc}"


def main() -> int:
    with CATALOG.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}

    validators = {
        "greenhouse": validate_greenhouse,
        "lever": validate_lever,
        "ashby": validate_ashby,
    }
    tasks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        for ats, validator in validators.items():
            for entry in payload.get(ats, []):
                tasks.append(executor.submit(validator, entry))
        results = [future.result() for future in tasks]

    failed = False
    for company, ok, detail in sorted(results):
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {company}: {detail}")
        failed = failed or not ok
    print(f"Validated {len(results)} configured boards")
    return 1 if failed or len(results) != 30 else 0


if __name__ == "__main__":
    sys.exit(main())
