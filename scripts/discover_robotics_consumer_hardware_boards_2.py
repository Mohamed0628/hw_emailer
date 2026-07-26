"""Second temporary discovery pool for robotics and consumer hardware boards."""

from __future__ import annotations

import concurrent.futures
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.discover_robotics_consumer_hardware_boards import (  # noqa: E402
    ALIASES,
    discover,
    existing_names,
)

CANDIDATES = [
    # Smart home, cameras, networking, and connected physical products
    "Zwift",
    "ButterflyMX",
    "Latch",
    "Rhombus Systems",
    "Flock Safety",
    "Meter",
    "Density",
    "Butlr",
    "Kisi",
    "OpenSpace",
    "Motive",
    "Geotab",
    "Hologram",
    "Plume",
    "Sierra Wireless",
    "Spot AI",
    "Ambient.ai",
    "Verkada",
    "Samsara",
    "Rapsodo",
    "Nix Biosensors",
    "Willow Innovations",
    "Elvie",
    "Yoto",
    "Tonies",
    "Airthings",
    "Nanit",
    "Owlet",
    "Hatch Baby",
    "Ring",
    "eero",
    "Ecobee",
    "Lutron Electronics",
    "Brava Home",
    "Suvie",
    "Ooni",
    "Anova Culinary",
    "Mill",
    "Nespresso",
    "SharkNinja",
    "Traeger Grills",
    "Weber-Stephen Products",
    # Displays, XR, audio, electronics, and fabrication hardware
    "Looking Glass Factory",
    "Light Field Lab",
    "Mojo Vision",
    "DigiLens",
    "Lumus",
    "Avegant",
    "Varjo",
    "Pimax",
    "HaptX",
    "Contact CI",
    "Teenage Engineering",
    "Master & Dynamic",
    "Shure Incorporated",
    "Sonos",
    "Bose Corporation",
    "GoPro",
    "Insta360",
    "Formlabs",
    "Glowforge",
    "Inkbit",
    "Mantle",
    "VulcanForms",
    "Nexa3D",
    "Seurat Technologies",
    "Desktop Metal",
    "UltiMaker",
    "LightForce Orthodontics",
    # Health, wearable, and consumer fitness hardware
    "Garmin",
    "Withings",
    "WHOOP",
    "Oura",
    "Tonal",
    "Peloton",
    "Hydrow",
    "Tempo Fitness",
    "Ergatta",
    "Vitruvian",
    "Lumen Metabolism",
    "Ultrahuman",
    "ŌURA",
    "Willow",
    "Owlet Baby Care",
    # Robotics research, industrial automation, and embodied AI
    "The AI Institute",
    "Toyota Research Institute",
    "Boston Dynamics",
    "Foundation Robotics",
    "The Bot Company",
    "Genesis AI",
    "Galbot",
    "Fourier Intelligence",
    "Unitree Robotics",
    "Dexai Robotics",
    "Chef Robotics",
    "Pickle Robot",
    "Ambi Robotics",
    "Dexterity",
    "Locus Robotics",
    "Bright Machines",
    "Path Robotics",
    "Third Wave Automation",
    "Outrider",
    "Scythe Robotics",
    "Electric Sheep Robotics",
    "Burro",
    "FarmWise",
    "Tortuga AgTech",
    "Brightpick",
    "Exotec",
    "Mujin",
    "Rapyuta Robotics",
    "Vecna Robotics",
    "Seegrid",
    "Slip Robotics",
    "RightHand Robotics",
    "Realtime Robotics",
    "Plus One Robotics",
    "GreyOrange",
    "Nomagic",
    "Sereact",
    "Sanctuary AI",
    "Sunday Robotics",
    "Dyna Robotics",
    "Generalist AI",
    "Nimble Robotics",
    "Promise Robotics",
    # Medical, rehabilitation, surgical, and assistive robotics
    "Neocis",
    "PROCEPT BioRobotics",
    "THINK Surgical",
    "Galen Robotics",
    "Mendaera",
    "Moon Surgical",
    "ForSight Robotics",
    "CMR Surgical",
    "Distalmotion",
    "Momentis Surgical",
    "EndoQuest Robotics",
    "Ekso Bionics",
    "Myomo",
    "ReWalk Robotics",
    "Synchron",
    "Precision Neuroscience",
    "Paradromics",
    "Science Corporation",
    "Blackrock Neurotech",
    "Phantom Neuro",
]

ALIASES.update(
    {
        "ButterflyMX": ["butterflymx", "butterfly-mx"],
        "Rhombus Systems": ["rhombus", "rhombussystems", "rhombus-systems"],
        "Flock Safety": ["flock", "flocksafety", "flock-safety"],
        "OpenSpace": ["openspace", "open-space"],
        "Nix Biosensors": ["nix", "nixbiosensors", "nix-biosensors"],
        "Willow Innovations": ["willow", "willowinnovations", "willow-innovations"],
        "Hatch Baby": ["hatch", "hatchbaby", "hatch-baby"],
        "Lutron Electronics": ["lutron", "lutronelectronics", "lutron-electronics"],
        "Looking Glass Factory": ["lookingglass", "looking-glass", "lookingglassfactory"],
        "Light Field Lab": ["lightfieldlab", "light-field-lab"],
        "Mojo Vision": ["mojo", "mojovision", "mojo-vision"],
        "Contact CI": ["contactci", "contact-ci"],
        "Master & Dynamic": ["masterdynamic", "master-dynamic", "masteranddynamic"],
        "Shure Incorporated": ["shure", "shureinc"],
        "Seurat Technologies": ["seurat", "seurattechnologies", "seurat-technologies"],
        "LightForce Orthodontics": ["lightforce", "lightforceorthodontics"],
        "Tempo Fitness": ["tempo", "tempofitness", "tempo-fitness"],
        "Lumen Metabolism": ["lumen", "lumenmetabolism"],
        "The AI Institute": ["theaiinstitute", "ai-institute", "aiinstitute"],
        "Toyota Research Institute": ["tri", "toyotaresearchinstitute"],
        "The Bot Company": ["thebotcompany", "bot-company", "botcompany"],
        "Foundation Robotics": ["foundation", "foundationrobotics", "foundation-robotics"],
        "PROCEPT BioRobotics": ["procept", "proceptbiorobotics", "procept-biorobotics"],
        "THINK Surgical": ["thinksurgical", "think-surgical"],
        "Galen Robotics": ["galen", "galenrobotics", "galen-robotics"],
        "Precision Neuroscience": ["precision", "precisionneuroscience", "precision-neuroscience"],
        "Science Corporation": ["science", "sciencecorp", "science-corporation"],
        "Blackrock Neurotech": ["blackrock", "blackrockneurotech", "blackrock-neurotech"],
        "Phantom Neuro": ["phantom", "phantomneuro", "phantom-neuro"],
    }
)


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
