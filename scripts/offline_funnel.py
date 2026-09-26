"""Fast, read-only funnel analysis over recovered alert jobs.

Uses stored descriptions and the same evaluation/resume logic as the application
runner. Does not open a browser, fill forms, write the application tracker, or submit.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import argparse
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import config
from src.alert_store import application_alert_jobs, load_alert_jobs
from src.apply.defense_gate import is_defense_or_clearance_job
from src.apply.policy import settings
from src.apply.profile import load_profile
from src.apply.registry import get_applicator
from src.evaluation import evaluate_jobs
from src.identity import is_workday_job
from src.resumes import load_resumes
from src.signals import is_minnesota


def target_market(location: str) -> str | None:
    text = " ".join((location or "").casefold().split())
    if not text:
        return None

    if is_minnesota(location):
        return "Minnesota"

    if re.search(r"\bcalifornia\b|(?:^|,)\s*ca\b", text) or any(
        city in text for city in (
            "san francisco", "bay area", "palo alto", "mountain view",
            "menlo park", "sunnyvale", "san jose", "los angeles", "san diego",
        )
    ):
        return "California"

    if "washington dc" not in text and "washington, d.c." not in text:
        if re.search(r"\bwashington\b|(?:^|,)\s*wa\b", text) or any(
            city in text for city in ("seattle", "bellevue", "redmond")
        ):
            return "Seattle/Washington"

    if re.search(r"\bnew york\b|(?:^|,)\s*ny\b", text):
        return "New York"

    return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only funnel report for recovered alert jobs; no browser or submissions."
    )
    parser.add_argument("--profile", type=Path, help="private candidate YAML")
    parser.add_argument("--minimum-fit", type=int, default=70)
    args = parser.parse_args(argv)

    profile = load_profile(args.profile)
    resumes = load_resumes(profile)
    jobs = application_alert_jobs(load_alert_jobs(config.alert_jobs_path()))
    evaluated = evaluate_jobs(jobs, resumes)

    hard_no = [j for j in evaluated if j.classification == "HARD_NO"]
    eligible = [j for j in evaluated if j.classification != "HARD_NO"]
    target = [j for j in eligible if target_market(j.location_str)]
    fit = [j for j in target if (j.resume_fit_score or 0) >= args.minimum_fit]

    defense = [j for j in fit if is_defense_or_clearance_job(j)]
    workday = [j for j in fit if not is_defense_or_clearance_job(j) and is_workday_job(j)]

    allowed = set(settings().get("allowed_auto_ats", []))
    automatic = []
    manual_ats = []
    for job in fit:
        if is_defense_or_clearance_job(job) or is_workday_job(job):
            continue
        adapter = get_applicator(job)
        if getattr(adapter, "automatic", True) and adapter.ats in allowed:
            automatic.append(job)
        else:
            manual_ats.append(job)

    scored = [j for j in eligible if j.resume_match]
    score_bands = Counter()
    for job in scored:
        score = job.resume_fit_score or 0
        if score >= 70:
            score_bands[">=70"] += 1
        elif score >= 55:
            score_bands["55-69"] += 1
        elif score > 0:
            score_bands["1-54"] += 1
        else:
            score_bands["0"] += 1

    print("\n==================== OFFLINE FUNNEL ====================")
    print(f"Recovered full-context jobs: {len(jobs)}")
    print(f"Rejected before application eligibility: {len(hard_no)}")
    print(f"Eligible hardware/new-grad jobs: {len(eligible)}")
    print(f"Eligible jobs actually resume-scored: {len(scored)}")
    print(f"Resume score bands among scored jobs: {dict(score_bands)}")
    print(f"Target markets (MN / CA / Seattle-WA / NY): {len(target)}")
    print(f"Target market + resume fit >= {args.minimum_fit}: {len(fit)}")
    print(f"  defense/clearance manual: {len(defense)}")
    print(f"  Workday manual: {len(workday)}")
    print(f"  unsupported/manual ATS: {len(manual_ats)}")
    print(f"  guarded auto-apply ATS candidates: {len(automatic)}")

    market_counts = Counter(target_market(j.location_str) for j in fit)
    category_counts = Counter(j.category or "uncategorized" for j in fit)
    resume_counts = Counter(j.selected_resume or "unselected" for j in fit)
    print("\n>=70 target-market breakdown:")
    print("  markets:", dict(market_counts))
    print("  categories:", dict(category_counts))
    print("  selected resumes:", dict(resume_counts))

    if automatic:
        print("\nGuarded auto-apply candidates (top 25 by fit):")
        for job in sorted(automatic, key=lambda j: (-(j.resume_fit_score or 0), j.company.casefold()))[:25]:
            print(
                f"  {job.resume_fit_score:>3}%  {job.company} | {job.title} | "
                f"{job.location_str} | {job.selected_resume} | {job.job_id}"
            )

    print("\nRead-only report: no pages opened, no forms filled, no application state changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
