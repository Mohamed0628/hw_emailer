"""Probe a second pool of commercial RF, robotics, and civil aviation targets."""

from __future__ import annotations

import concurrent.futures

from validate_rf_robotics_avionics_boards import discover

CANDIDATES = [
    # Connected hardware, RF, GNSS, and IoT
    "Plume",
    "Motive",
    "Spot AI",
    "Ambient.ai",
    "Matterport",
    "Geotab",
    "Lytx",
    "Arlo Technologies",
    "Alarm.com",
    "Hologram",
    "Sierra Wireless",
    "Semtech",
    "Silicon Labs",
    "Taoglas",
    "PCTEL",
    # Commercial and industrial robotics
    "1X",
    "Sanctuary AI",
    "Bear Robotics",
    "Relay Robotics",
    "Starship Technologies",
    "Cartken",
    "Nimble",
    "Vayu Robotics",
    "Matic Robots",
    "Weave Robotics",
    "Promise Robotics",
    "BotBuilt",
    "Wandercraft",
    "RobCo",
    "Vention",
    "NEURA Robotics",
    "Wandelbots",
    "Gatik",
    "Waabi",
    "Mentee Robotics",
    # Civilian drones, aircraft, and aviation autonomy
    "DroneDeploy",
    "Flytrex",
    "DroneUp",
    "Matternet",
    "Percepto",
    "Gather AI",
    "Corvus Robotics",
    "Flyby Robotics",
    "Rotor Technologies",
    "Rain",
    "Swoop Aero",
    "Wingcopter",
    "Parallel Flight Technologies",
    "AeroVect",
    "Airspace Link",
]


def main() -> None:
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(lambda company: discover(company, None), CANDIDATES))
    for company, matches in sorted(results):
        if matches:
            print(f"[FOUND] {company}: {' | '.join(matches)}")
        else:
            print(f"[MISSING] {company}: no Greenhouse, Lever, or Ashby match")


if __name__ == "__main__":
    main()
