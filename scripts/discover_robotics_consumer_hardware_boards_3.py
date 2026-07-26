"""Final temporary discovery pool for robotics and consumer hardware boards."""

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
    # Wearable, diagnostic, and personal-health devices
    "AliveCor",
    "Eko Health",
    "TytoCare",
    "Empatica",
    "Kernel",
    "Interaxon",
    "Muse",
    "OpenBCI",
    "EMOTIV",
    "Biobeat",
    "NuraLogix",
    "Current Health",
    "BioIntelliSense",
    "VitalConnect",
    "Movano Health",
    "Circular",
    "RingConn",
    "Amazfit",
    "Zepp Health",
    "Apollo Neuro",
    "Sensate",
    "Pulsetto",
    "Therabody",
    "Hyperice",
    "Eight Sleep",
    # Sports, cameras, imaging, and sensing hardware
    "Hudl",
    "Veo Technologies",
    "Pixellot",
    "Rapsodo",
    "TrackMan",
    "FlightScope",
    "Hawk-Eye Innovations",
    "Catapult Sports",
    "PlaySight",
    "GoPro",
    "Insta360",
    "Matterport",
    "Leica Geosystems",
    "Ouster",
    "Luminar",
    "AEye",
    "Innoviz Technologies",
    "Arbe Robotics",
    # XR, display, haptics, and audio hardware
    "Looking Glass Factory",
    "Mojo Vision",
    "DigiLens",
    "Lumus",
    "Avegant",
    "Varjo",
    "HaptX",
    "Ultraleap",
    "Tanvas",
    "Actronika",
    "bHaptics",
    "Shokz",
    "Audeze",
    "Jabra",
    "Devialet",
    # Home robotics and smart appliances
    "Aiper",
    "Mammotion",
    "Yarbo",
    "Labrador Systems",
    "Intuition Robotics",
    "Roborock",
    "Narwal Robotics",
    "Dreame Technology",
    "Ecovacs Robotics",
    "SwitchBot",
    "Brava",
    "Suvie",
    "Ooni",
    "Anova Culinary",
    "Ember Technologies",
    "Bartesian",
    "Molekule",
    "Blueair",
    "Coway",
    # Additive manufacturing and physical-product platforms
    "Inkbit",
    "Mantle 3D",
    "VulcanForms",
    "Nexa3D",
    "Carbon 3D",
    "Desktop Metal",
    "UltiMaker",
    "Formlabs",
    "Glowforge",
    "Fictiv",
    "Hubs",
    # Medical, surgical, rehabilitation, and assistive robotics
    "Neocis",
    "Galen Robotics",
    "PROCEPT BioRobotics",
    "THINK Surgical",
    "Mendaera",
    "Proprio",
    "Augmedics",
    "Synchron",
    "Paradromics",
    "Precision Neuroscience",
    "Science Corporation",
    "Blackrock Neurotech",
    "Phantom Neuro",
    "Ekso Bionics",
    "Myomo",
    "ReWalk Robotics",
    "Wandercraft",
    # Additional robotics and embodied-AI companies
    "The AI Institute",
    "Boston Dynamics",
    "Foundation Robotics",
    "The Bot Company",
    "Genesis AI",
    "Skild AI",
    "OpenMind",
    "Sereact",
    "Nomagic",
    "Dexai Robotics",
    "Brightpick",
    "Scythe Robotics",
    "Burro",
    "Electric Sheep Robotics",
    "FarmWise",
    "Tortuga AgTech",
    "Starship Technologies",
    "Cartken",
    "Vayu Robotics",
]

ALIASES.update(
    {
        "Eko Health": ["eko", "ekohealth", "eko-health"],
        "OpenBCI": ["openbci", "open-bci"],
        "Current Health": ["currenthealth", "current-health"],
        "BioIntelliSense": ["biointellisense", "bio-intellisense"],
        "Movano Health": ["movano", "movanohealth", "movano-health"],
        "Apollo Neuro": ["apolloneuro", "apollo-neuro"],
        "Veo Technologies": ["veo", "veotechnologies", "veo-technologies"],
        "Hawk-Eye Innovations": ["hawkeye", "hawk-eye", "hawkeyeinnovations"],
        "Catapult Sports": ["catapult", "catapultsports"],
        "Innoviz Technologies": ["innoviz", "innoviztechnologies"],
        "Arbe Robotics": ["arbe", "arberobotics", "arbe-robotics"],
        "Looking Glass Factory": ["lookingglass", "lookingglassfactory"],
        "Mojo Vision": ["mojo", "mojovision"],
        "Narwal Robotics": ["narwal", "narwalrobotics"],
        "Dreame Technology": ["dreame", "dreametechnology"],
        "Ecovacs Robotics": ["ecovacs", "ecovacsrobotics"],
        "Ember Technologies": ["ember", "embertechnologies"],
        "Mantle 3D": ["mantle", "mantle3d", "mantle-3d"],
        "Carbon 3D": ["carbon", "carbon3d", "carbon-3d"],
        "PROCEPT BioRobotics": ["procept", "proceptbiorobotics"],
        "THINK Surgical": ["think", "thinksurgical"],
        "Precision Neuroscience": ["precision", "precisionneuroscience"],
        "Science Corporation": ["science", "sciencecorp", "sciencecorporation"],
        "Blackrock Neurotech": ["blackrock", "blackrockneurotech"],
        "The AI Institute": ["theaiinstitute", "aiinstitute"],
        "The Bot Company": ["thebotcompany", "botcompany"],
        "Foundation Robotics": ["foundation", "foundationrobotics"],
        "Electric Sheep Robotics": ["electricsheep", "electric-sheep-robotics"],
        "Tortuga AgTech": ["tortuga", "tortugaagtech"],
        "Starship Technologies": ["starship", "starshiptechnologies"],
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
