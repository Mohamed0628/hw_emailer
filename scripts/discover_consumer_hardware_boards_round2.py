#!/usr/bin/env python3
"""Second temporary live validation pass for exact consumer-hardware boards."""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path
from typing import Any

import requests

TIMEOUT = 12

CANDIDATES: list[tuple[str, str, str]] = [
    ("SharkNinja", "greenhouse", "sharkninjaoperatingllc"),
    ("Sharp Electronics", "greenhouse", "sharpelectronics"),
    ("Delart", "greenhouse", "delartech"),
    ("ALTEN Technology USA", "greenhouse", "altentechnologyusa"),
    ("Emporia Energy", "greenhouse", "emporiarevolutionizinghomeenergy"),
    ("Sandbar", "ashby", "sandbar"),
    ("Sesame", "ashby", "sesame"),
    ("Noia Labs", "ashby", "noialabs"),
    ("Human Archive", "ashby", "humanarchive"),
    ("Afference", "ashby", "afference"),
    ("Sabi", "ashby", "sabi"),
    ("Pronoia", "ashby", "pronoia"),
    ("Epia Neuro", "ashby", "epianeuro"),
    ("Humble Robotics", "lever", "humble-robotics"),
    ("Valinor Enterprises", "ashby", "valinor"),
    ("Capable Labs", "ashby", "Capable"),
    ("Flux", "ashby", "flux"),
    ("Vayyar", "greenhouse", "vayyar"),
    ("Lumen Technologies Consumer Hardware", "greenhouse", "lumen"),
    ("Brilliant Labs", "ashby", "brilliantlabs"),
    ("Rabbit", "ashby", "rabbit"),
    ("Limitless", "ashby", "limitless"),
    ("Bee AI", "ashby", "bee"),
    ("Rewind", "ashby", "rewind"),
    ("Plaid Hardware", "ashby", "plaid"),
    ("OpenBCI", "ashby", "openbci"),
    ("Neurable", "greenhouse", "neurable"),
    ("Paradromics", "greenhouse", "paradromics"),
    ("Precision Neuroscience", "greenhouse", "precisionneuroscience"),
    ("Synchron", "greenhouse", "synchron"),
    ("iRhythm", "greenhouse", "irhythm"),
    ("Biolinq", "greenhouse", "biolinq"),
    ("Owlet", "greenhouse", "owletcare"),
    ("Senseonics", "greenhouse", "senseonics"),
    ("Elvie", "greenhouse", "elvie"),
    ("Hydrow", "greenhouse", "hydrow"),
    ("Therabody", "greenhouse", "therabody"),
    ("Hyperice", "greenhouse", "hyperice"),
    ("Sphero", "greenhouse", "sphero"),
    ("Light Field Lab", "greenhouse", "lightfieldlab"),
    ("Brelyon", "greenhouse", "brelyon"),
    ("Mojo Vision", "greenhouse", "mojovision"),
    ("Leia", "greenhouse", "leiainc"),
    ("xMEMS Labs", "greenhouse", "xmemslabs"),
    ("DSP Concepts", "greenhouse", "dspconcepts"),
    ("RealWear", "lever", "realwear"),
    ("Empatica", "lever", "empatica"),
    ("FightCamp", "lever", "fightcamp"),
    ("Nanoleaf", "lever", "nanoleaf"),
    ("Withings", "lever", "withings"),
]

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}


def rows_for(ats: str, payload: Any) -> list[dict[str, Any]]:
    if ats == "lever":
        return payload if isinstance(payload, list) else []
    if isinstance(payload, dict):
        rows = payload.get("jobs") or []
        return rows if isinstance(rows, list) else []
    return []


def title(row: dict[str, Any]) -> str:
    return str(row.get("title") or row.get("text") or "").strip()


def url(row: dict[str, Any]) -> str:
    return str(
        row.get("absolute_url")
        or row.get("hostedUrl")
        or row.get("jobUrl")
        or row.get("applyUrl")
        or ""
    ).strip()


def probe(company: str, ats: str, slug: str) -> dict[str, Any] | None:
    try:
        response = requests.get(
            ENDPOINTS[ats].format(slug=slug),
            timeout=TIMEOUT,
            headers={"User-Agent": "hw-emailer-board-validator/1.0"},
        )
        if response.status_code != 200:
            return None
        rows = rows_for(ats, response.json())
        if not rows:
            return None
        return {
            "company": company,
            "ats": ats,
            "slug": slug,
            "count": len(rows),
            "samples": [
                {"title": title(row), "url": url(row)}
                for row in rows[:4]
                if isinstance(row, dict)
            ],
        }
    except (requests.RequestException, ValueError, TypeError):
        return None


def main() -> int:
    matches: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(probe, *candidate) for candidate in CANDIDATES]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                matches.append(result)

    matches.sort(key=lambda item: item["company"].casefold())
    Path("consumer-hardware-discovery-round2.json").write_text(
        json.dumps(matches, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Found {len(matches)} live exact boards")
    for item in matches:
        sample = item["samples"][0] if item["samples"] else {}
        print(
            f"{item['company']} | {item['ats']} | {item['slug']} | "
            f"{item['count']} | {sample.get('title', '')} | {sample.get('url', '')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
