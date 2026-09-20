"""Conservative defense / government-clearance automation exclusion.

Jobs matching this gate remain discoverable and reviewable, but browser automation
must not fill or submit them.

Export-control wording (for example ITAR/EAR or U.S.-person requirements) is not,
by itself, evidence that a role is defense- or clearance-related.
"""
from __future__ import annotations

import re

from ..models import Job

DEFENSE_MANUAL_REASON = "Application: Manual — defense/government-clearance related role"

DEFENSE_COMPANIES = {
    "anduril",
    "astranis",
    "bae systems",
    "blue origin",
    "booz allen hamilton",
    "collins aerospace",
    "general dynamics",
    "hermeus",
    "l3harris",
    "leidos",
    "lockheed martin",
    "northrop grumman",
    "palantir",
    "radiant industries",
    "raytheon",
    "rocket lab",
    "rtx",
    "shield ai",
    "spacex",
}

_PATTERNS = tuple(re.compile(p, re.I) for p in (
    r"\b(?:active\s+)?security clearance\b",
    r"\b(?:secret|top secret|ts\/sci) clearance\b",
    r"\b(?:dod|department of defense)\b",
    r"\bclassified (?:program|work|environment|information)\b",
    r"\bdefense contractor\b",
    r"\bgovernment clearance\b",
))


def is_defense_or_clearance_job(job: Job) -> bool:
    company = job.company.casefold().strip()
    if any(name in company for name in DEFENSE_COMPANIES):
        return True
    text = "\n".join(filter(None, (job.title, job.description or "")))
    return any(pattern.search(text) for pattern in _PATTERNS)
