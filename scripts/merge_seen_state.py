#!/usr/bin/env python3
"""Merge a generated seen-jobs state with the latest state from main.

The scheduled workflow can finish after another commit has reached ``main``.
Instead of pushing from a stale checkout, it saves the generated state, refreshes
against ``origin/main``, and unions both state dictionaries with this script.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"state must be a JSON object: {path}")
    return {
        str(key): value
        for key, value in payload.items()
        if isinstance(value, dict)
    }


def merge_states(
    current: dict[str, dict[str, Any]],
    generated: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Union states, keeping the earliest known first_seen date per job."""
    merged = dict(current)
    for job_id, incoming in generated.items():
        existing = merged.get(job_id)
        if not existing:
            merged[job_id] = incoming
            continue

        combined = dict(existing)
        combined.update(
            {
                key: value
                for key, value in incoming.items()
                if value not in (None, "")
            }
        )
        dates = [
            str(value)
            for value in (existing.get("first_seen"), incoming.get("first_seen"))
            if value
        ]
        if dates:
            combined["first_seen"] = min(dates)
        merged[job_id] = combined
    return dict(sorted(merged.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge two seen-jobs JSON state files")
    parser.add_argument("current", type=Path)
    parser.add_argument("generated", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    merged = merge_states(_load(args.current), _load(args.generated))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
