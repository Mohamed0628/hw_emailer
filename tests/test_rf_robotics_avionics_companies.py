"""Configuration tests for the RF, robotics, and civil aviation expansion."""

from __future__ import annotations

import yaml

from src import config


CATALOG = "companies_rf_robotics_avionics.yaml"
EXPECTED_COMPANIES = {
    "Tarana Wireless",
    "Celona",
    "Pivotal Commware",
    "Federated Wireless",
    "Parallel Wireless",
    "XCOM Labs",
    "Kymeta",
    "Skyworks Solutions",
    "Qorvo",
    "Qualcomm",
    "Covariant",
    "Dusty Robotics",
    "Canvas",
    "RightHand Robotics",
    "GrayMatter Robotics",
    "Realtime Robotics",
    "Plus One Robotics",
    "Fox Robotics",
    "Slip Robotics",
    "Seegrid",
    "Joby Aviation",
    "Wisk Aero",
    "BETA Technologies",
    "Electra.aero",
    "REGENT",
    "Elroy Air",
    "Pyka",
    "Boom Supersonic",
    "Merlin Labs",
    "Whisper Aero",
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
    ]


def test_catalog_contains_exactly_30_companies():
    payload = _load(CATALOG)
    assert set(_names(payload)) == EXPECTED_COMPANIES
    assert len(_names(payload)) == 30
    assert len(payload.get("greenhouse", [])) == 27
    assert len(payload.get("workday", [])) == 3


def test_catalog_names_are_unique():
    names = [name.casefold() for name in _names(_load(CATALOG))]
    assert len(names) == len(set(names))


def test_catalog_does_not_duplicate_existing_catalogs():
    existing_names: set[str] = set()
    for name in ("companies.yaml", "companies_regional.yaml"):
        existing_names.update(item.casefold() for item in _names(_load(name)))
    new_names = {item.casefold() for item in _names(_load(CATALOG))}
    assert existing_names.isdisjoint(new_names)


def test_runtime_catalog_includes_all_new_companies():
    config.companies.cache_clear()
    runtime_names = {name.casefold() for name in _names(config.companies())}
    expected_names = {name.casefold() for name in EXPECTED_COMPANIES}
    assert expected_names <= runtime_names


def test_entries_have_required_ats_identifiers():
    payload = _load(CATALOG)
    for entry in payload.get("greenhouse", []):
        assert entry.get("company") and entry.get("token")
    for entry in payload.get("workday", []):
        assert all(entry.get(key) for key in ("company", "tenant", "wd_num", "site"))
        assert entry.get("search_texts")
        assert entry.get("fetch_details") is True


def test_civil_aviation_catalog_excludes_defense_first_employers():
    names = {name.casefold() for name in _names(_load(CATALOG))}
    excluded = {
        "anduril",
        "shield ai",
        "hermeus",
        "saronic",
        "kratos defense",
        "bae systems",
        "general dynamics mission systems",
    }
    assert names.isdisjoint(excluded)
