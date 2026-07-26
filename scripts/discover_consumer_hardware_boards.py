#!/usr/bin/env python3
"""Temporary live discovery for additional consumer-hardware ATS boards."""

from __future__ import annotations

import concurrent.futures
import json
from pathlib import Path
from typing import Any

import requests

TIMEOUT = 12

CANDIDATES: dict[str, list[str]] = {
    "GoPro": ["goprocareers", "gopro"],
    "Framework Computer": ["frameworkcomputer", "framework"],
    "Life360": ["life360"],
    "Cricut": ["cricut"],
    "Sonos": ["sonos"],
    "Owl Labs": ["owllabs", "owl-labs"],
    "Ember": ["ember", "embertechnologies"],
    "Brilliant Labs": ["brilliantlabs", "brilliant-labs"],
    "Rabbit": ["rabbit", "rabbitinc", "rabbit-inc"],
    "Limitless": ["limitless", "limitlessai", "limitless-ai"],
    "Ultrahuman": ["ultrahuman"],
    "Owlet": ["owlet", "owletcare"],
    "Senseonics": ["senseonics"],
    "iRhythm": ["irhythm", "irhythmtech"],
    "Biolinq": ["biolinq"],
    "Empatica": ["empatica"],
    "Hydrow": ["hydrow"],
    "Tempo": ["tempo", "tempofit", "tempo-fit"],
    "Therabody": ["therabody"],
    "Hyperice": ["hyperice"],
    "FightCamp": ["fightcamp", "fight-camp"],
    "Nanoleaf": ["nanoleaf"],
    "Sphero": ["sphero"],
    "Bird Buddy": ["birdbuddy", "bird-buddy"],
    "Looking Glass Factory": ["lookingglassfactory", "looking-glass-factory"],
    "Light Field Lab": ["lightfieldlab", "light-field-lab"],
    "Brelyon": ["brelyon"],
    "Mojo Vision": ["mojovision", "mojo-vision"],
    "Leia": ["leia", "leiainc", "leia-inc"],
    "Lumafield": ["lumafield"],
    "xMEMS Labs": ["xmemslabs", "xmems"],
    "DSP Concepts": ["dspconcepts", "dsp-concepts"],
    "Yubico": ["yubico"],
    "Ajax Systems": ["ajax", "ajaxsystems", "ajax-systems"],
    "DISHER": ["disher"],
    "Alertus Technologies": ["alertus", "alertus-technologies"],
    "OpenAI": ["openai"],
    "Egra": ["egra", "Egra"],
    "Elvie": ["elvie"],
    "Vuzix": ["vuzix"],
    "RealWear": ["realwear"],
    "Pison": ["pison"],
    "Synchron": ["synchron"],
    "Paradromics": ["paradromics"],
    "Precision Neuroscience": ["precisionneuroscience", "precision-neuroscience"],
    "Neurable": ["neurable"],
    "Aktiia": ["aktiia"],
    "Withings": ["withings"],
    "Shure": ["shure"],
    "xTool": ["xtool", "x-tool"],
    "Glowforge": ["glowforge"],
    "Prusa Research": ["prusa", "prusaresearch"],
    "Molekule": ["molekule"],
    "Bevi": ["bevi"],
    "Savant Systems": ["savant", "savantsystems"],
    "ecobee": ["ecobee"],
    "Wyze Labs": ["wyze", "wyzelabs"],
    "Lutron": ["lutron"],
    "Chamberlain Group": ["chamberlain", "chamberlaingroup"],
    "iRobot": ["irobot"],
    "Skullcandy": ["skullcandy"],
    "Corsair": ["corsair"],
    "Razer": ["razer"],
    "Logitech": ["logitech"],
    "Bose": ["bose"],
    "SharkNinja": ["sharkninja", "shark-ninja"],
    "Belkin": ["belkin"],
    "Sena Technologies": ["sena", "senatechnologies"],
    "Tile": ["tile"],
    "RingConn": ["ringconn"],
    "Circular": ["circular"],
    "Dexai Robotics": ["dexai", "dexairobotics"],
    "Ecovacs Robotics": ["ecovacs"],
    "Roborock": ["roborock"],
    "Narwal Robotics": ["narwal", "narwalrobotics"],
    "Aiper": ["aiper"],
    "Mammotion": ["mammotion"],
    "Anker Innovations": ["anker", "ankerinnovations"],
    "Govee": ["govee"],
    "Vayyar": ["vayyar"],
    "Aqara": ["aqara"],
    "Brava": ["brava"],
    "June Oven": ["juneoven", "june-oven"],
    "Moxie": ["moxie"],
    "Embodied": ["embodied"],
    "Aira": ["aira"],
    "Eight": ["eight"],
}

ATS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}


def _jobs(ats: str, payload: Any) -> list[dict[str, Any]]:
    if ats == "lever":
        return payload if isinstance(payload, list) else []
    if isinstance(payload, dict):
        rows = payload.get("jobs") or []
        return rows if isinstance(rows, list) else []
    return []


def _title(row: dict[str, Any]) -> str:
    return str(row.get("title") or row.get("text") or "").strip()


def _url(row: dict[str, Any]) -> str:
    return str(
        row.get("absolute_url")
        or row.get("hostedUrl")
        or row.get("jobUrl")
        or row.get("applyUrl")
        or ""
    ).strip()


def probe(company: str, ats: str, slug: str) -> dict[str, Any] | None:
    url = ATS[ats].format(slug=slug)
    try:
        response = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": "hw-emailer-board-validator/1.0"})
        if response.status_code != 200:
            return None
        payload = response.json()
        rows = _jobs(ats, payload)
        if not rows:
            return None
        samples = [
            {"title": _title(row), "url": _url(row)}
            for row in rows[:3]
            if isinstance(row, dict)
        ]
        return {
            "company": company,
            "ats": ats,
            "slug": slug,
            "count": len(rows),
            "samples": samples,
        }
    except (requests.RequestException, ValueError, TypeError):
        return None


def main() -> int:
    tasks = [
        (company, ats, slug)
        for company, slugs in CANDIDATES.items()
        for slug in slugs
        for ats in ATS
    ]
    matches: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as pool:
        futures = [pool.submit(probe, *task) for task in tasks]
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                matches.append(result)

    matches.sort(key=lambda item: (item["company"].casefold(), item["ats"], item["slug"]))
    Path("consumer-hardware-discovery.json").write_text(
        json.dumps(matches, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Found {len(matches)} live candidate boards")
    for item in matches:
        sample = item["samples"][0] if item["samples"] else {}
        print(
            f"{item['company']} | {item['ats']} | {item['slug']} | "
            f"{item['count']} | {sample.get('title', '')} | {sample.get('url', '')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
