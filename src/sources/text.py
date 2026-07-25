"""Shared text cleanup helpers for ATS payloads."""

from __future__ import annotations

import re
from html import unescape

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def plain_text(value: object) -> str:
    """Convert HTML or arbitrary text into normalized plain text."""
    if value is None:
        return ""
    text = _TAG_RE.sub(" ", str(value))
    text = unescape(text)
    return _WS_RE.sub(" ", text).strip()
