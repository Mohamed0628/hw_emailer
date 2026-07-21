"""Source base class + shared HTTP helpers."""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

import requests

from .. import config
from ..models import Job

log = logging.getLogger(__name__)


def _http_cfg() -> dict[str, Any]:
    return config.settings().get("http", {}) or {}


def make_session() -> requests.Session:
    s = requests.Session()
    ua = _http_cfg().get("user_agent", "intern-pos-emailer/1.0")
    s.headers.update({"User-Agent": ua, "Accept": "application/json"})
    return s


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    json_body: Optional[dict] = None,
    params: Optional[dict] = None,
) -> Optional[Any]:
    """GET/POST returning parsed JSON, with retries + timeout. None on failure."""
    cfg = _http_cfg()
    timeout = cfg.get("timeout_seconds", 20)
    retries = int(cfg.get("retries", 2))
    backoff = cfg.get("retry_backoff_seconds", 2)
    delay = cfg.get("per_request_delay", 0.0)

    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            if delay:
                time.sleep(delay)
            resp = session.request(
                method, url, json=json_body, params=params, timeout=timeout
            )
            if resp.status_code == 404:
                log.warning("404 (not found): %s", url)
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:  # noqa: BLE001 - we want to isolate any failure
            last_err = exc
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    log.warning("request failed after retries: %s (%s)", url, last_err)
    return None


def request_text(session: requests.Session, url: str) -> Optional[str]:
    """GET returning response text, with retries + timeout. None on failure."""
    cfg = _http_cfg()
    timeout = cfg.get("timeout_seconds", 20)
    retries = int(cfg.get("retries", 2))
    backoff = cfg.get("retry_backoff_seconds", 2)
    delay = cfg.get("per_request_delay", 0.0)

    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            if delay:
                time.sleep(delay)
            resp = session.get(url, timeout=timeout)
            if resp.status_code == 404:
                log.warning("404 (not found): %s", url)
                return None
            resp.raise_for_status()
            return resp.text
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
    log.warning("request failed after retries: %s (%s)", url, last_err)
    return None


class Source(ABC):
    """A source fetches and returns a list of normalized Job objects.

    Implementations must never raise on network/parse errors — they should log
    and return whatever they managed to collect, so one dead endpoint can't kill
    the whole run.
    """

    name: str = "source"

    @abstractmethod
    def fetch(self, session: requests.Session) -> list[Job]:
        ...

    def safe_fetch(self, session: requests.Session) -> list[Job]:
        try:
            jobs = self.fetch(session)
        except Exception as exc:  # noqa: BLE001
            log.warning("source %s crashed: %s", self.name, exc)
            return []
        cap = config.settings().get("max_jobs_per_source", 0) or 0
        if cap and len(jobs) > cap:
            jobs = jobs[:cap]
        log.info("source %s -> %d jobs", self.name, len(jobs))
        return jobs
