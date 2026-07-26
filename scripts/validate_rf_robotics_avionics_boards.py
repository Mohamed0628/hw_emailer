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

EXTRA_CANDIDATES = [
    # RF, wireless, connectivity, and IoT hardware
    "Morse Micro",
    "Skylo Technologies",
    "Swift Navigation",
    "Hubble Network",
    "Blues",
    "Particle",
    "Samsara",
    "Verkada",
    "Calix",
    "Airgain",
    "Eridan",
    "Cambium Networks",
    "Airspan",
    "SiTime",
    "Movandi",
    # Commercial and industrial robotics
    "Anyware Robotics",
    "RIVR",
    "Droyd",
    "Human Computer Lab",
    "Scythe Robotics",
    "Burro",
    "FarmWise",
    "Tortuga AgTech",
    "Brightpick",
    "Exotec",
    "Mujin",
    "Rapyuta Robotics",
    "Berkshire Grey",
    "Vecna Robotics",
    "Electric Sheep Robotics",
    # Civilian aviation, electric aircraft, and air mobility
    "Odys Aviation",
    "Airhart Aeronautics",
    "MightyFly",
    "Skyryse",
    "JetZero",
    "Natilus",
    "Pivotal",
    "Eviation",
    "magniX",
    "ZeroAvia",
    "Ampaire",
    "Surf Air Mobility",
    "Loft Dynamics",
    "Airspace Intelligence",
    "uAvionix",
]

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
    "Morse Micro": ["morse", "morse-micro", "morsemicro"],
    "Skylo Technologies": ["skylo", "skylo-technologies", "skylotechnologies"],
    "Swift Navigation": ["swift", "swift-navigation", "swiftnavigation"],
    "Hubble Network": ["hubble", "hubble-network", "hubblenetwork"],
    "Blues": ["blues", "blues-wireless", "blueswireless"],
    "Particle": ["particle"],
    "Samsara": ["samsara"],
    "Verkada": ["verkada"],
    "Calix": ["calix"],
    "Airgain": ["airgain"],
    "Eridan": ["eridan", "eridancommunications"],
    "Cambium Networks": ["cambium", "cambium-networks", "cambiumnetworks"],
    "Airspan": ["airspan"],
    "SiTime": ["sitime", "si-time"],
    "Movandi": ["movandi"],
    "Anyware Robotics": ["anyware", "anyware-robotics", "anywarerobotics"],
    "RIVR": ["rivr"],
    "Droyd": ["droyd"],
    "Human Computer Lab": ["humancomputerlab", "human-computer-lab"],
    "Scythe Robotics": ["scythe", "scythe-robotics", "scytherobotics"],
    "Burro": ["burro"],
    "FarmWise": ["farmwise"],
    "Tortuga AgTech": ["tortuga", "tortuga-agtech", "tortugaagtech"],
    "Brightpick": ["brightpick"],
    "Exotec": ["exotec"],
    "Mujin": ["mujin"],
    "Rapyuta Robotics": ["rapyuta", "rapyuta-robotics", "rapyutarobotics"],
    "Berkshire Grey": ["berkshire-grey", "berkshiregrey"],
    "Vecna Robotics": ["vecna", "vecna-robotics", "vecnarobotics"],
    "Electric Sheep Robotics": ["electric-sheep", "electric-sheep-robotics", "electricsheep"],
    "Odys Aviation": ["odys", "odys-aviation", "odysaviation"],
    "Airhart Aeronautics": ["airhart", "airhart-aeronautics", "airhartaeronautics"],
    "MightyFly": ["mighty-fly", "mightyfly"],
    "Skyryse": ["skyryse"],
    "JetZero": ["jet-zero", "jetzero"],
    "Natilus": ["natilus"],
    "Pivotal": ["pivotal"],
    "Eviation": ["eviation"],
    "magniX": ["magnix"],
    "ZeroAvia": ["zero-avia", "zeroavia"],
    "Ampaire": ["ampaire"],
    "Surf Air Mobility": ["surf-air-mobility", "surfair", "surfairmobility"],
    "Loft Dynamics": ["loft", "loft-dynamics", "loftdynamics"],
    "Airspace Intelligence": ["airspace", "airspace-intelligence", "airspaceintelligence"],
    "uAvionix": ["u-avionix", "uavionix"],
}


def token_variants(company: str, configured: str | None = None) -> list[str]:
    lower = company.casefold().replace("&", " and ")
    words = re.findall(r"[a-z0-9]+", lower)
    variants = {"".join(words), "-".join(words)}
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


def probe_greenhouse(token: str) -> tuple[bool, int, str]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    response = requests.get(url, timeout=TIMEOUT)
    if response.status_code != 200:
        return False, 0, ""
    payload = response.json()
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return False, 0, ""
    sample = jobs[0] if jobs else {}
    return True, len(jobs), f"{sample.get('title', '')} @ {sample.get('absolute_url', '')}"


def probe_lever(token: str) -> tuple[bool, int, str]:
    url = f"https://api.lever.co/v0/postings/{token}"
    response = requests.get(url, params={"mode": "json"}, timeout=TIMEOUT)
    if response.status_code != 200:
        return False, 0, ""
    payload = response.json()
    if not isinstance(payload, list):
        return False, 0, ""
    sample = payload[0] if payload else {}
    return True, len(payload), f"{sample.get('text', '')} @ {sample.get('hostedUrl', '')}"


def probe_ashby(token: str) -> tuple[bool, int, str]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{token}"
    response = requests.get(url, timeout=TIMEOUT)
    if response.status_code != 200:
        return False, 0, ""
    payload = response.json()
    jobs = payload.get("jobs") if isinstance(payload, dict) else None
    if not isinstance(jobs, list):
        return False, 0, ""
    sample = jobs[0] if jobs else {}
    return True, len(jobs), f"{sample.get('title', '')} @ {sample.get('jobUrl', '')}"


def discover(company: str, configured: str | None) -> tuple[str, list[str]]:
    matches: list[str] = []
    for token in token_variants(company, configured):
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


def main() -> int:
    with CATALOG.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}

    configured: dict[str, str | None] = {}
    for source_entries in payload.values():
        if not isinstance(source_entries, list):
            continue
        for entry in source_entries:
            configured[str(entry["company"])] = entry.get("token")

    companies = list(configured)
    companies.extend(company for company in EXTRA_CANDIDATES if company not in configured)
    entries = [(company, configured.get(company)) for company in companies]

    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(lambda item: discover(*item), entries))

    for company, matches in sorted(results):
        if matches:
            print(f"[FOUND] {company}: {' | '.join(matches)}")
        else:
            print(f"[MISSING] {company}: no Greenhouse, Lever, or Ashby match")
    return 0


if __name__ == "__main__":
    sys.exit(main())
