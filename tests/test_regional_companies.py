"""Configuration tests for the regional PCB and robotics expansion."""

from __future__ import annotations

import yaml

from src import config


def _regional() -> dict:
    path = config.CONFIG_DIR / "companies_regional.yaml"
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _names(payload: dict) -> list[str]:
    return [
        str(entry["company"])
        for entries in payload.values()
        if isinstance(entries, list)
        for entry in entries
    ]


def test_regional_expansion_contains_exactly_30_companies():
    regional = _regional()
    assert len(_names(regional)) == 30


def test_regional_company_names_are_unique():
    names = [name.casefold() for name in _names(_regional())]
    assert len(names) == len(set(names))


def test_regional_companies_do_not_duplicate_base_catalog():
    base = config._load_yaml("companies.yaml")  # noqa: SLF001
    base_names = {name.casefold() for name in _names(base)}
    regional_names = {name.casefold() for name in _names(_regional())}
    assert base_names.isdisjoint(regional_names)


def test_runtime_catalog_includes_all_regional_companies():
    config.companies.cache_clear()
    runtime_names = {name.casefold() for name in _names(config.companies())}
    expected_names = {name.casefold() for name in _names(_regional())}
    assert expected_names <= runtime_names


def test_regional_entries_have_required_ats_identifiers():
    regional = _regional()
    for entry in regional.get("ashby", []):
        assert entry.get("company") and entry.get("token")
    for entry in regional.get("greenhouse", []):
        assert entry.get("company") and entry.get("token")
    for entry in regional.get("workday", []):
        assert all(entry.get(key) for key in ("company", "tenant", "wd_num", "site"))
        assert entry.get("search_texts")
        assert entry.get("fetch_details") is True
