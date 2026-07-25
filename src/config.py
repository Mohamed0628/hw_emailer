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


@lru_cache(maxsize=None)
def filters() -> dict[str, Any]:
    return _load_yaml("filters.yaml")


@lru_cache(maxsize=None)
def github_lists() -> dict[str, Any]:
    return _load_yaml("github_lists.yaml")


@lru_cache(maxsize=None)
def companies() -> dict[str, Any]:
    return _load_yaml("companies.yaml")


@lru_cache(maxsize=None)
def direct_companies() -> dict[str, Any]:
    return _load_yaml("direct_companies.yaml")


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
