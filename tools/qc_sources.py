from __future__ import annotations

import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import yaml


CONFIG_PATH = Path("config/companies.yaml")
TIMEOUT = 20

ssl_context = ssl.create_default_context()

HEADERS = {
    "Accept": "application/json,text/html,*/*",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 Chrome/150 Safari/537.36"
    ),
}


def request_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
) -> tuple[int, Any]:
    body = None

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers=HEADERS,
        method=method,
    )

    with urllib.request.urlopen(
        request,
        timeout=TIMEOUT,
        context=ssl_context,
    ) as response:
        content = response.read().decode("utf-8", errors="replace")
        return response.status, json.loads(content)


def request_page(url: str) -> tuple[int, str]:
    request = urllib.request.Request(
        url,
        headers=HEADERS,
        method="GET",
    )

    with urllib.request.urlopen(
        request,
        timeout=TIMEOUT,
        context=ssl_context,
    ) as response:
        content = response.read().decode("utf-8", errors="replace")
        return response.status, content


def result(
    ats: str,
    company: str,
    status: str,
    jobs: int | str,
    detail: str,
) -> dict[str, Any]:
    return {
        "ats": ats,
        "company": company,
        "status": status,
        "jobs": jobs,
        "detail": detail,
    }


def test_greenhouse(entry: dict[str, Any]) -> dict[str, Any]:
    company = entry.get("company", "Unknown")
    token = entry.get("token")

    if not token:
        return result("greenhouse", company, "CONFIG ERROR", "-", "Missing token")

    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    status, data = request_json(url)
    jobs = data.get("jobs", [])

    return result("greenhouse", company, "OK", len(jobs), url)


def test_lever(entry: dict[str, Any]) -> dict[str, Any]:
    company = entry.get("company", "Unknown")
    token = entry.get("token")

    if not token:
        return result("lever", company, "CONFIG ERROR", "-", "Missing token")

    encoded_token = urllib.parse.quote(str(token), safe="-_.")
    url = f"https://api.lever.co/v0/postings/{encoded_token}?mode=json"
    status, data = request_json(url)

    jobs = data if isinstance(data, list) else []

    return result("lever", company, "OK", len(jobs), url)


def test_ashby(entry: dict[str, Any]) -> dict[str, Any]:
    company = entry.get("company", "Unknown")
    token = entry.get("token")

    if not token:
        return result("ashby", company, "CONFIG ERROR", "-", "Missing token")

    encoded_token = urllib.parse.quote(str(token), safe="-_.")
    url = (
        "https://api.ashbyhq.com/posting-api/job-board/"
        f"{encoded_token}?includeCompensation=true"
    )
    status, data = request_json(url)

    jobs = data.get("jobs", []) if isinstance(data, dict) else []

    return result("ashby", company, "OK", len(jobs), url)


def test_workday(entry: dict[str, Any]) -> dict[str, Any]:
    company = entry.get("company", "Unknown")
    tenant = entry.get("tenant")
    wd_num = entry.get("wd_num")
    site = entry.get("site")

    missing = [
        field
        for field, value in {
            "tenant": tenant,
            "wd_num": wd_num,
            "site": site,
        }.items()
        if value in (None, "")
    ]

    if missing:
        return result(
            "workday",
            company,
            "CONFIG ERROR",
            "-",
            "Missing " + ", ".join(missing),
        )

    url = (
        f"https://{tenant}.wd{wd_num}.myworkdayjobs.com/"
        f"wday/cxs/{tenant}/{site}/jobs"
    )

    payload = {
        "appliedFacets": {},
        "limit": 20,
        "offset": 0,
        "searchText": "",
    }

    status, data = request_json(url, method="POST", payload=payload)

    returned = len(data.get("jobPostings", []))
    total = data.get("total", returned)

    return result(
        "workday",
        company,
        "OK",
        total,
        f"Returned {returned}; {url}",
    )


def test_icims(entry: dict[str, Any]) -> dict[str, Any]:
    company = entry.get("company", "Unknown")
    base_url = entry.get("url")

    if not base_url:
        return result("icims", company, "CONFIG ERROR", "-", "Missing url")

    url = str(base_url).rstrip("/") + "/search?ss=1"
    status, page = request_page(url)

    lowered = page.lower()

    if "page not found" in lowered or "404 not found" in lowered:
        return result("icims", company, "BROKEN PAGE", "-", url)

    job_markers = [
        "iCIMS_JobsTable",
        "iCIMS_JobsTableRow",
        "jobTitle",
        "jobs/",
        "iCIMS",
    ]

    marker_found = any(marker.lower() in lowered for marker in job_markers)

    if marker_found:
        return result(
            "icims",
            company,
            "REACHABLE",
            "HTML",
            url,
        )

    return result(
        "icims",
        company,
        "REVIEW",
        "HTML",
        f"Page loaded but iCIMS markers were unclear: {url}",
    )


TESTERS = {
    "greenhouse": test_greenhouse,
    "lever": test_lever,
    "ashby": test_ashby,
    "workday": test_workday,
    "icims": test_icims,
}


def main() -> int:
    if not CONFIG_PATH.exists():
        print(f"ERROR: Could not find {CONFIG_PATH}")
        return 1

    with CONFIG_PATH.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file) or {}

    results: list[dict[str, Any]] = []

    print("=" * 90)
    print("HW_EMAILER SOURCE QUALITY CONTROL")
    print("=" * 90)

    for ats, tester in TESTERS.items():
        entries = config.get(ats, [])

        print()
        print(f"[{ats.upper()}] Testing {len(entries)} entries")
        print("-" * 90)

        for entry in entries:
            company = entry.get("company", "Unknown")

            try:
                test_result = tester(entry)

            except urllib.error.HTTPError as error:
                test_result = result(
                    ats,
                    company,
                    f"HTTP {error.code}",
                    "-",
                    error.geturl(),
                )

            except urllib.error.URLError as error:
                test_result = result(
                    ats,
                    company,
                    "NETWORK ERROR",
                    "-",
                    str(error.reason),
                )

            except json.JSONDecodeError:
                test_result = result(
                    ats,
                    company,
                    "BAD RESPONSE",
                    "-",
                    "Endpoint did not return valid JSON",
                )

            except Exception as error:
                test_result = result(
                    ats,
                    company,
                    "ERROR",
                    "-",
                    f"{type(error).__name__}: {error}",
                )

            results.append(test_result)

            print(
                f"{test_result['status']:<14} "
                f"{ats:<11} "
                f"{company:<38} "
                f"jobs={test_result['jobs']}"
            )

    broken_statuses = {
        "CONFIG ERROR",
        "BROKEN PAGE",
        "BAD RESPONSE",
        "NETWORK ERROR",
        "ERROR",
        "REVIEW",
    }

    broken = [
        item
        for item in results
        if item["status"] in broken_statuses
        or str(item["status"]).startswith("HTTP ")
    ]

    valid_zero = [
        item
        for item in results
        if item["status"] == "OK" and item["jobs"] == 0
    ]

    print()
    print("=" * 90)
    print("SUMMARY")
    print("=" * 90)
    print(f"Total entries tested: {len(results)}")
    print(f"Needs attention:      {len(broken)}")
    print(f"Valid but zero jobs:  {len(valid_zero)}")

    if broken:
        print()
        print("ENTRIES THAT NEED ATTENTION")
        print("-" * 90)

        for item in broken:
            print(
                f"{item['ats']:<11} | "
                f"{item['company']:<38} | "
                f"{item['status']:<14} | "
                f"{item['detail']}"
            )

    if valid_zero:
        print()
        print("VALID ENDPOINTS CURRENTLY RETURNING ZERO JOBS")
        print("-" * 90)

        for item in valid_zero:
            print(f"{item['ats']:<11} | {item['company']}")

    output_path = Path("data/source_qc_report.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(results, indent=2),
        encoding="utf-8",
    )

    print()
    print(f"Full JSON report saved to: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
