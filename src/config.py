"""Configuration + secrets loading."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"

load_dotenv(ROOT / ".env")


def _load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _merge_dicts(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge configuration dictionaries without mutating inputs."""
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _merge_company_configs(*names: str) -> dict[str, Any]:
    """Merge ATS company lists while preserving source order."""
    merged: dict[str, Any] = {}
    for name in names:
        payload = _load_yaml(name)
        for source, entries in payload.items():
            if isinstance(entries, list):
                merged.setdefault(source, []).extend(entries)
            elif source not in merged:
                merged[source] = entries
    return merged


@lru_cache(maxsize=None)
def filters() -> dict[str, Any]:
    base = _load_yaml("filters.yaml")
    taxonomy = _load_yaml("category_taxonomy.yaml")
    merged = _merge_dicts(base, taxonomy)

    # The taxonomy is a complete replacement for the legacy three-category
    # block, not an additive merge. Keeping the old categories would create
    # duplicate keyword matches and unstable labels.
    if taxonomy.get("categories"):
        merged["categories"] = taxonomy["categories"]
    if taxonomy.get("category_priority"):
        merged["category_priority"] = taxonomy["category_priority"]

    return merged


@lru_cache(maxsize=None)
def github_lists() -> dict[str, Any]:
    return _load_yaml("github_lists.yaml")


@lru_cache(maxsize=None)
def companies() -> dict[str, Any]:
    return _merge_company_configs(
        "companies.yaml",
        "companies_regional.yaml",
        "companies_rf_robotics_avionics.yaml",
        "companies_robotics_consumer_hardware.yaml",
        "companies_consumer_hardware_more.yaml",
        "companies_hardware_expansion.yaml",
        "companies_batch_01.yaml",
        "companies_batch_02.yaml",
        "companies_batch_03.yaml",
        "companies_batch_04.yaml",
        "companies_batch_05.yaml",
        "companies_batch_06.yaml",
        "companies_batch_07.yaml",
        "companies_batch_08.yaml",
        "companies_batch_09.yaml",
        "companies_batch_10.yaml",
        "companies_batch_11.yaml",
        "companies_batch_12.yaml",
        "companies_batch_13.yaml",
        "companies_batch_14.yaml",
        "companies_batch_15.yaml",
        "companies_batch_16.yaml",
        "companies_batch_17.yaml",
        "companies_batch_18.yaml",
        "companies_batch_19.yaml",
        "companies_batch_20.yaml",
        "companies_batch_21.yaml",
        "companies_batch_22.yaml",
        "companies_batch_23.yaml",
        "companies_batch_24.yaml",
        "companies_batch_25.yaml",
        "companies_batch_26.yaml",
        "companies_batch_27.yaml",
        "companies_batch_28.yaml",
        "companies_batch_29.yaml",
        "companies_batch_30.yaml",
    )


@lru_cache(maxsize=None)
def direct_companies() -> dict[str, Any]:
    return _merge_company_configs(
        "direct_companies.yaml",
        "direct_companies_batch_01.yaml",
    )


@lru_cache(maxsize=None)
def minnesota_medtech() -> dict[str, Any]:
    return _load_yaml("minnesota_medtech.yaml")


@lru_cache(maxsize=None)
def settings() -> dict[str, Any]:
    return _load_yaml("settings.yaml")


def state_path() -> Path:
    rel = settings().get("state_file", "data/seen_jobs.json")
    return ROOT / rel


def secrets() -> dict[str, str]:
    """Return notification secrets from the environment (may be empty)."""
    keys = [
        "GMAIL_USER",
        "GMAIL_APP_PASSWORD",
        "EMAIL_TO",
        "TWILIO_ACCOUNT_SID",
        "TWILIO_AUTH_TOKEN",
        "TWILIO_FROM",
        "SMS_TO",
    ]
    return {key: os.environ.get(key, "") for key in keys}
