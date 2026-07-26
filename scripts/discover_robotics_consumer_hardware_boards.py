"""Temporarily discover active public ATS boards for robotics and consumer hardware."""

from __future__ import annotations

import concurrent.futures
import re
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 8

CANDIDATES = [
    # Consumer devices, wearables, audio, smart home, and connected products
    "Framework Computer",
    "Oura",
    "WHOOP",
    "Nothing",
    "Rabbit",
    "PLAUD",
    "Core Devices",
    "Pebble",
    "Daylight Computer",
    "Limitless AI",
    "Bee AI",
    "Friend",
    "Iyo",
    "Brilliant Labs",
    "Sonos",
    "Roku",
    "GoPro",
    "Peloton",
    "Tonal",
    "Hydrow",
    "Tempo",
    "Lumen",
    "Levels",
    "Ultrahuman",
    "Withings",
    "Logitech",
    "Bose",
    "Shure",
    "ecobee",
    "SimpliSafe",
    "Level Home",
    "Brilliant Home Technology",
    "Nanoleaf",
    "Rachio",
    "Airthings",
    "Sense",
    "Awair",
    "Wyze",
    "Lutron",
    "Nanit",
    "Owlet",
    "Hatch",
    "Molekule",
    "LIFX",
    "Govee",
    "Aqara",
    "SwitchBot",
    "reMarkable",
    "Supernote",
    "Flic",
    "Tile",
    "Ember",
    "Fellow Products",
    "Tovala",
    "SharkNinja",
    "Traeger",
    "Weber",
    "iFIT",
    "Ergatta",
    "Shokz",
    "Skullcandy",
    "Devialet",
    "Magic Leap",
    "Vuzix",
    "XREAL",
    "Nreal",
    "Formlabs",
    "Glowforge",
    "Prusa Research",
    "Bambu Lab",
    "Snapmaker",
    "Airthings",
    "Nuki",
    "Aqara",
    "Eight Sleep",
    "Oura Health",
    "WHOOP Labs",
    "Framework",
    "Nothing Technology",
    "Rabbit Inc",
    "Plaud AI",
    "Daylight",
    "Core Devices Inc",
    # Commercial, industrial, home, logistics, and medical robotics
    "Covariant",
    "Dusty Robotics",
    "Canvas Construction",
    "RightHand Robotics",
    "Realtime Robotics",
    "Plus One Robotics",
    "Slip Robotics",
    "Seegrid",
    "Exotec",
    "Mujin",
    "Rapyuta Robotics",
    "Berkshire Grey",
    "Vecna Robotics",
    "Electric Sheep Robotics",
    "Scythe Robotics",
    "Burro",
    "FarmWise",
    "Tortuga AgTech",
    "Brightpick",
    "Anyware Robotics",
    "Sanctuary AI",
    "Bear Robotics",
    "Relay Robotics",
    "Starship Technologies",
    "Cartken",
    "Nimble Robotics",
    "Vayu Robotics",
    "Weave Robotics",
    "Promise Robotics",
    "BotBuilt",
    "Wandercraft",
    "NEURA Robotics",
    "Wandelbots",
    "Gatik",
    "Mentee Robotics",
    "Sereact",
    "Nomagic",
    "GreyOrange",
    "HAI Robotics",
    "Symbotic",
    "AutoStore",
    "Fabric",
    "Persona AI",
    "Skild AI",
    "Generalist AI",
    "Dyna Robotics",
    "Sunday Robotics",
    "Labrador Systems",
    "Intuition Robotics",
    "Enchanted Tools",
    "Tombot",
    "RobCo",
    "Robust AI",
    "Standard Bots",
    "Collaborative Robotics",
    "Cobot",
    "Physical Intelligence",
    "Fauna Robotics",
    "Human Computer Lab",
    "Revise Robotics",
    "Reflex Robotics",
    "Matic Robots",
    "1X",
    "Corvus Robotics",
    "Gather AI",
    "RIVR",
    "Waabi",
    "Moon Surgical",
    "Mendaera",
    "ForSight Robotics",
    "CMR Surgical",
    "Distalmotion",
    "Memic Innovative Surgery",
    "Momentis Surgical",
    "EndoQuest Robotics",
    "Moonshot AI Robotics",
]

ALIASES: dict[str, list[str]] = {
    "Framework Computer": ["framework", "frameworkcomputer"],
    "Oura": ["oura", "ouraring", "oura-health"],
    "WHOOP": ["whoop", "whoopinc", "whoop-labs"],
    "Nothing": ["nothing", "nothingtechnology", "nothing-technology"],
    "Rabbit": ["rabbit", "rabbitinc", "rabbit-inc"],
    "PLAUD": ["plaud", "plaudai", "plaud-ai"],
    "Core Devices": ["coredevices", "core-devices"],
    "Pebble": ["pebble", "coredevices", "core-devices"],
    "Daylight Computer": ["daylight", "daylightcomputer", "daylight-computer"],
    "Limitless AI": ["limitless", "limitlessai", "limitless-ai"],
    "Bee AI": ["bee", "beeai", "bee-ai"],
    "Brilliant Labs": ["brilliantlabs", "brilliant-labs"],
    "Level Home": ["level", "levelhome", "level-home"],
    "Brilliant Home Technology": ["brilliant", "brillianthome", "brilliant-home"],
    "Fellow Products": ["fellow", "fellowproducts", "fellow-products"],
    "Magic Leap": ["magicleap", "magic-leap"],
    "Formlabs": ["formlabs"],
    "Bambu Lab": ["bambulab", "bambu-lab"],
    "Canvas Construction": ["canvas", "canvasconstruction", "canvas-construction"],
    "RightHand Robotics": ["righthandrobotics", "right-hand-robotics", "righthand"],
    "Realtime Robotics": ["realtimerobotics", "realtime-robotics", "realtime"],
    "Plus One Robotics": ["plusonerobotics", "plus-one-robotics", "plusone"],
    "Berkshire Grey": ["berkshiregrey", "berkshire-grey"],
    "Electric Sheep Robotics": ["electricsheep", "electric-sheep", "electric-sheep-robotics"],
    "Tortuga AgTech": ["tortuga", "tortugaagtech", "tortuga-agtech"],
    "Anyware Robotics": ["anyware", "anywarerobotics", "anyware-robotics"],
    "Sanctuary AI": ["sanctuary", "sanctuaryai", "sanctuary-ai"],
    "Starship Technologies": ["starship", "starshiptechnologies", "starship-technologies"],
    "Nimble Robotics": ["nimble", "nimblerobotics", "nimble-robotics"],
    "Promise Robotics": ["promise", "promiserobotics", "promise-robotics"],
    "HAI Robotics": ["hairobotics", "hai-robotics"],
    "Collaborative Robotics": ["collaborative", "collaborativerobotics", "collaborative-robotics"],
    "Moon Surgical": ["moonsurgical", "moon-surgical"],
    "ForSight Robotics": ["forsight", "forsightrobotics", "forsight-robotics"],
    "CMR Surgical": ["cmrsurgical", "cmr-surgical"],
    "Memic Innovative Surgery": ["memic", "memicinnovative", "memic-innovative-surgery"],
    "Momentis Surgical": ["momentis", "momentissurgical", "momentis-surgical"],
    "EndoQuest Robotics": ["endoquest", "endoquestrobotics", "endoquest-robotics"],
}


def existing_names() -> set[str]:
    names: set[str] = set()
    for filename in (
        "companies.yaml",
        "companies_regional.yaml",
        "companies_rf_robotics_avionics.yaml",
        "direct_companies.yaml",
    ):
        path = ROOT / "config" / filename
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fh:
            payload = yaml.safe_load(fh) or {}
        for entries in payload.values():
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if isinstance(entry, dict) and entry.get("company"):
                    names.add(str(entry["company"]).casefold())
    return names


def token_variants(company: str) -> list[str]:
    lower = company.casefold().replace("&", " and ")
    words = re.findall(r"[a-z0-9]+", lower)
    variants = {"".join(words), "-".join(words)}
    removable = {
        "inc", "company", "computer", "technology", "technologies", "labs",
        "robotics", "surgical", "systems", "products", "home", "health",
        "innovative", "construction", "ai",
    }
    reduced = [word for word in words if word not in removable]
    if reduced:
        variants.add("".join(reduced))
        variants.add("-".join(reduced))
    variants.update(ALIASES.get(company, []))
    return sorted(item for item in variants if item)


def probe_greenhouse(token: str) -> tuple[bool, int, str]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    response = requests.get(url, timeout=TIMEOUT)
    if response.status_code != 200:
        return False, 0, ""
    payload = response.json()
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list) or not jobs:
        return False, 0, ""
    sample = jobs[0]
    return True, len(jobs), f"{sample.get('title', '')} @ {sample.get('absolute_url', '')}"


def probe_lever(token: str) -> tuple[bool, int, str]:
    url = f"https://api.lever.co/v0/postings/{token}"
    response = requests.get(url, params={"mode": "json"}, timeout=TIMEOUT)
    if response.status_code != 200:
        return False, 0, ""
    payload = response.json()
    if not isinstance(payload, list) or not payload:
        return False, 0, ""
    sample = payload[0]
    return True, len(payload), f"{sample.get('text', '')} @ {sample.get('hostedUrl', '')}"


def probe_ashby(token: str) -> tuple[bool, int, str]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    response = requests.get(url, timeout=TIMEOUT)
    if response.status_code != 200:
        return False, 0, ""
    payload = response.json()
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    listed = [job for job in jobs or [] if job.get("isListed") is not False]
    if not listed:
        return False, 0, ""
    sample = listed[0]
    return True, len(listed), f"{sample.get('title', '')} @ {sample.get('jobUrl', '')}"


def discover(company: str) -> tuple[str, list[str]]:
    matches: list[str] = []
    for token in token_variants(company):
        for ats, probe in (
            ("greenhouse", probe_greenhouse),
            ("lever", probe_lever),
            ("ashby", probe_ashby),
        ):
            try:
                ok, count, sample = probe(token)
            except Exception:  # noqa: BLE001
                continue
            if ok:
                matches.append(f"{ats}:{token}:{count}:{sample}")
    return company, sorted(set(matches))


def main() -> None:
    existing = existing_names()
    candidates: list[str] = []
    seen: set[str] = set()
    for company in CANDIDATES:
        folded = company.casefold()
        if folded in existing or folded in seen:
            continue
        seen.add(folded)
        candidates.append(company)

    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as executor:
        results = list(executor.map(discover, candidates))

    for company, matches in sorted(results):
        if matches:
            print(f"[FOUND] {company}: {' | '.join(matches)}")
        else:
            print(f"[MISSING] {company}: no active Greenhouse, Lever, or Ashby board")


if __name__ == "__main__":
    main()
