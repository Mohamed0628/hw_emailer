"""Tests for conflict-safe merging of the scheduled workflow state."""

from __future__ import annotations

from scripts.merge_seen_state import merge_states


def test_merge_unions_remote_and_generated_jobs():
    current = {
        "remote-only": {
            "company": "Remote Corp",
            "title": "Hardware Engineer",
            "first_seen": "2026-07-26",
        }
    }
    generated = {
        "generated-only": {
            "company": "Generated Corp",
            "title": "Electrical Engineer",
            "first_seen": "2026-07-26",
        }
    }

    merged = merge_states(current, generated)

    assert set(merged) == {"remote-only", "generated-only"}


def test_merge_keeps_earliest_first_seen_and_latest_metadata():
    current = {
        "same-job": {
            "company": "Example",
            "title": "Hardware Engineer",
            "url": "https://example.com/old",
            "first_seen": "2026-07-24",
        }
    }
    generated = {
        "same-job": {
            "company": "Example",
            "title": "Hardware Engineer I",
            "url": "https://example.com/new",
            "first_seen": "2026-07-26",
        }
    }

    merged = merge_states(current, generated)

    assert merged["same-job"]["first_seen"] == "2026-07-24"
    assert merged["same-job"]["title"] == "Hardware Engineer I"
    assert merged["same-job"]["url"] == "https://example.com/new"


def test_merge_is_sorted_for_stable_commits():
    merged = merge_states(
        {"z-job": {"first_seen": "2026-07-26"}},
        {"a-job": {"first_seen": "2026-07-26"}},
    )

    assert list(merged) == ["a-job", "z-job"]
