"""Configuration tests for the robotics and consumer-hardware expansion."""

from __future__ import annotations

import yaml

from src import config

CATALOG = "companies_robotics_consumer_hardware.yaml"
EXPECTED_COMPANIES = {
    "Fellow Products",
    "Formlabs",
    "Magic Leap",
    "Nanit",
    "Nothing",
    "Oura",
    "Peloton",
    "Roku",
    "SimpliSafe",
    "iFIT",
    "Butlr",
    "Mill",
    "Traeger Grills",
    "Willow Innovations",
    "Zwift",
    "Geotab",
    "Hologram",
    "LightForce Orthodontics",
    "Motive",
    "OpenSpace",
    "Plume",
    "Seurat Technologies",
    "Carbon 3D",
    "Catapult Sports",
    "Fictiv",
    "Hudl",
    "Nimble Robotics",
    "Tovala",
    "Latch",
    "Rhombus Systems",
    "BioIntelliSense",
    "Eko Health",
    "Veo Technologies",
    "Promise Robotics",
    "Toyota Research Institute",
    "Iyo",
    "Level Home",
    "PLAUD",
    "Tonal",
    "WHOOP",
    "ButterflyMX",
    "Flock Safety",
    "Meter",
    "Hawk-Eye Innovations",
    "Kernel",
    "Dyna Robotics",
    "Generalist AI",
    "Sereact",
    "Sunday Robotics",
    "The Bot Company",
}


def _load(name: str) -> dict:
    path = config.CONFIG_DIR / name
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _names(payload: dict) -> list[str]:
    return [
        str(entry["company"])
        for entries in payload.values()
        if isinstance(entries, list)
        for entry in entries
        if isinstance(entry, dict) and entry.get("company")
    ]


def test_catalog_contains_exactly_50_companies():
    payload = _load(CATALOG)
    assert set(_names(payload)) == EXPECTED_COMPANIES
    assert len(_names(payload)) == 50
    assert len(payload.get("greenhouse", [])) == 27
    assert len(payload.get("lever", [])) == 8
    assert len(payload.get("ashby", [])) == 15


def test_catalog_company_names_are_unique():
    names = [name.casefold() for name in _names(_load(CATALOG))]
    assert len(names) == len(set(names))


def test_catalog_does_not_duplicate_existing_catalogs():
    existing_names: set[str] = set()
    for name in (
        "companies.yaml",
        "companies_regional.yaml",
        "companies_rf_robotics_avionics.yaml",
        "direct_companies.yaml",
    ):
        existing_names.update(item.casefold() for item in _names(_load(name)))
    new_names = {item.casefold() for item in _names(_load(CATALOG))}
    assert existing_names.isdisjoint(new_names)


def test_runtime_catalog_includes_all_new_companies():
    config.companies.cache_clear()
    runtime_names = {name.casefold() for name in _names(config.companies())}
    expected_names = {name.casefold() for name in EXPECTED_COMPANIES}
    assert expected_names <= runtime_names


def test_entries_have_required_public_ats_identifiers():
    payload = _load(CATALOG)
    for source in ("greenhouse", "lever", "ashby"):
        for entry in payload.get(source, []):
            assert entry.get("company") and entry.get("token")


def test_expansion_uses_only_lightweight_full_board_sources():
    payload = _load(CATALOG)
    assert set(payload) == {"greenhouse", "lever", "ashby"}
