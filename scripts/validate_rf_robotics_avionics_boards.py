"""Temporarily validate the new public ATS board identifiers during PR review."""

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
        if response.status_code != 200:
            return company, False, f"Greenhouse HTTP {response.status_code}: {url}"
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
            return company, False, f"Greenhouse payload missing jobs list: {url}"
        return company, True, f"Greenhouse OK, {len(payload['jobs'])} jobs"
    except Exception as exc:  # noqa: BLE001
        return company, False, f"Greenhouse error: {exc}"


def validate_workday(entry: dict) -> tuple[str, bool, str]:
    company = str(entry["company"])
    tenant = str(entry["tenant"])
    wd_num = entry["wd_num"]
    site = str(entry["site"])
    url = f"https://{tenant}.wd{wd_num}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    body = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": "intern"}
    try:
        response = requests.post(url, json=body, timeout=TIMEOUT)
        if response.status_code != 200:
            return company, False, f"Workday HTTP {response.status_code}: {url}"
        payload = response.json()
        if not isinstance(payload, dict) or "jobPostings" not in payload:
            return company, False, f"Workday payload missing jobPostings: {url}"
        return company, True, f"Workday OK, total={payload.get('total', 'unknown')}"
    except Exception as exc:  # noqa: BLE001
        return company, False, f"Workday error: {exc}"


def main() -> int:
    with CATALOG.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}

    tasks: list[tuple] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        for entry in payload.get("greenhouse", []):
            tasks.append(executor.submit(validate_greenhouse, entry))
        for entry in payload.get("workday", []):
            tasks.append(executor.submit(validate_workday, entry))

        results = [future.result() for future in tasks]

    failed = False
    for company, ok, detail in sorted(results):
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {company}: {detail}")
        failed = failed or not ok

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
