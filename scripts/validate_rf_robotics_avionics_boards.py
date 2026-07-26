"""Temporarily discover and validate public ATS boards during PR review."""

from __future__ import annotations

import concurrent.futures
import re
import sys
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "config" / "companies_rf_robotics_avionics.yaml"
TIMEOUT = 12

MANUAL_ALIASES: dict[str, list[str]] = {
    "BETA Technologies": ["beta", "beta-technologies", "betatechnologies"],
    "Boom Supersonic": ["boom", "boom-supersonic", "boomsupersonic"],
    "Canvas": ["canvas", "canvas-construction", "canvasconstruction"],
    "Celona": ["celona", "celonaio"],
    "Covariant": ["covariant", "covariantai"],
    "Dusty Robotics": ["dusty", "dusty-robotics", "dustyrobotics"],
    "Electra.aero": ["electra", "electra-aero", "electraero"],
    "Elroy Air": ["elroy", "elroy-air", "elroyair"],
    "Federated Wireless": ["federated", "federated-wireless", "federatedwireless"],
    "Fox Robotics": ["fox", "fox-robotics", "foxrobotics"],
    "GrayMatter Robotics": ["graymatter", "graymatter-robotics", "graymatterrobotics"],
    "Joby Aviation": ["joby", "joby-aviation", "jobyaviation"],
    "Kymeta": ["kymeta"],
    "Merlin Labs": ["merlin", "merlin-labs", "merlinlabs"],
    "Parallel Wireless": ["parallel", "parallel-wireless", "parallelwireless"],
    "Pivotal Commware": ["pivotal", "pivotal-commware", "pivotalcommware"],
    "Plus One Robotics": ["plusone", "plus-one", "plus-one-robotics", "plusonerobotics"],
    "Pyka": ["pyka"],
    "REGENT": ["regent", "regent-craft", "regentcraft"],
    "Realtime Robotics": ["realtime", "realtime-robotics", "realtimerobotics"],
    "RightHand Robotics": ["righthand", "right-hand-robotics", "righthandrobotics"],
    "Seegrid": ["seegrid"],
    "Slip Robotics": ["slip", "slip-robotics", "sliprobotics"],
    "Tarana Wireless": ["tarana", "tarana-wireless", "taranawireless"],
    "Whisper Aero": ["whisper", "whisper-aero", "whisperaero"],
    "Wisk Aero": ["wisk", "wisk-aero", "wiskaero"],
    "XCOM Labs": ["xcom", "xcom-labs", "xcomlabs"],
    "Skyworks Solutions": ["skyworks", "skyworks-solutions", "skyworkssolutions"],
    "Qorvo": ["qorvo"],
    "Qualcomm": ["qualcomm"],
}


def token_variants(company: str, configured: str | None = None) -> list[str]:
    lower = company.casefold().replace("&", " and ")
    words = re.findall(r"[a-z0-9]+", lower)
    variants = {
        "".join(words),
        "-".join(words),
    }
    removable = {
        "technologies",
        "technology",
        "robotics",
        "wireless",
        "aviation",
        "aero",
        "labs",
        "solutions",
    }
    reduced = [word for word in words if word not in removable]
    if reduced:
        variants.add("".join(reduced))
        variants.add("-".join(reduced))
    if configured:
        variants.add(configured)
    variants.update(MANUAL_ALIASES.get(company, []))
    return sorted(item for item in variants if item)


def probe_greenhouse(token: str) -> tuple[bool, int]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    response = requests.get(url, timeout=TIMEOUT)
    if response.status_code != 200:
        return False, 0
    payload = response.json()
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    return isinstance(jobs, list), len(jobs or [])


def probe_lever(token: str) -> tuple[bool, int]:
    url = f"https://api.lever.co/v0/postings/{token}"
    response = requests.get(url, params={"mode": "json"}, timeout=TIMEOUT)
    if response.status_code != 200:
        return False, 0
    payload = response.json()
    return isinstance(payload, list), len(payload) if isinstance(payload, list) else 0


def probe_ashby(token: str) -> tuple[bool, int]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    response = requests.get(url, timeout=TIMEOUT)
    if response.status_code != 200:
        return False, 0
    payload = response.json()
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    return isinstance(jobs, list), len(jobs or [])


def discover(company: str, configured: str | None) -> tuple[str, list[str]]:
    matches: list[str] = []
    for token in token_variants(company, configured):
        for ats, probe in (
            ("greenhouse", probe_greenhouse),
            ("lever", probe_lever),
            ("ashby", probe_ashby),
        ):
            try:
                ok, count = probe(token)
            except Exception:  # noqa: BLE001
                continue
            if ok:
                matches.append(f"{ats}:{token}:{count}")
    return company, sorted(set(matches))


def main() -> int:
    with CATALOG.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}

    entries: list[tuple[str, str | None]] = []
    for source_entries in payload.values():
        if not isinstance(source_entries, list):
            continue
        for entry in source_entries:
            entries.append((str(entry["company"]), entry.get("token")))

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(lambda item: discover(*item), entries))

    missing = False
    for company, matches in sorted(results):
        if matches:
            print(f"[FOUND] {company}: {' | '.join(matches)}")
        else:
            print(f"[MISSING] {company}: no Greenhouse, Lever, or Ashby match")
            missing = True
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
