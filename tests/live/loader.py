"""Read the scenario tables.

Scenarios are JSON, not Python, for the same reason the script and the prompts
are: the people who should be adding a safeguarding turn are not the people who
should be editing test code. Adding a case is adding an object to a list.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SCENARIO_DIR = Path(__file__).parent / "scenarios"

REPEAT_ENV = "MSAT_LIVE_REPEAT"


def scenarios(name: str) -> list[dict]:
    """The scenario table ``name``, as a list of dicts."""
    data = json.loads((SCENARIO_DIR / f"{name}.json").read_text(encoding="utf-8"))
    rows = list(data["scenarios"])
    seen = [row["id"] for row in rows]
    duplicates = sorted({row for row in seen if seen.count(row) > 1})
    if duplicates:
        raise ValueError(f"{name}.json has duplicate scenario id(s): {duplicates}")
    return rows


def ids(table: list[dict]) -> list[str]:
    return [row["id"] for row in table]


def describe(row: dict) -> str:
    """The scenario's own account of why it exists, for the failure message."""
    why = row.get("why") or ""
    return "\n".join(why) if isinstance(why, list) else why


def repeats() -> int:
    """How many times to put each scenario to the model.

    One by default. Raise it when you want to know whether a scenario is decided
    the same way every time — a guard that is right four times in five is not a
    guard, and a single green run is exactly how that stays unnoticed.
    """
    try:
        return max(1, int(os.getenv(REPEAT_ENV, "1")))
    except ValueError:
        return 1
