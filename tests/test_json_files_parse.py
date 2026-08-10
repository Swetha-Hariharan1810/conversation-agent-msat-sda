"""Every JSON file this project ships must parse.

This exists because ``langgraph.json`` was broken three times in one week, each
time by terminal output being pasted onto the end of it, and each time it went
unnoticed. Nothing in a normal ``pytest`` run opens that file, so the repository
looked healthy while the graph manifest could not be read at all — and the file
holds the pointer to ``.env``, so the failure took the live tests' credentials
with it.

A JSON file that does not parse is never intentional, and the check costs
nothing. It covers the manifests, the script and spec the agent loads, and the
scenario tables the live tests read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

SEARCH = ("*.json", "data/*.json", "tests/live/scenarios/*.json", ".github/**/*.json")


def _json_files() -> list[Path]:
    found = {path for pattern in SEARCH for path in REPO_ROOT.glob(pattern) if path.is_file()}
    return sorted(found)


@pytest.mark.parametrize(
    "path", _json_files(), ids=[str(p.relative_to(REPO_ROOT)) for p in _json_files()]
)
def test_it_parses(path: Path):
    text = path.read_text(encoding="utf-8")
    try:
        json.loads(text)
    except json.JSONDecodeError as exc:
        line = text.splitlines()[exc.lineno - 1] if exc.lineno <= len(text.splitlines()) else ""
        pytest.fail(
            f"{path.relative_to(REPO_ROOT)} is not valid JSON: {exc.msg} at line {exc.lineno}.\n"
            f"  the line reads: {line.strip()[:120]}\n"
            f"  if that looks like something pasted in by accident, it was."
        )


def test_the_graph_manifest_still_points_at_the_graph():
    """The two lines in langgraph.json anything depends on.

    ``graphs`` is what ``langgraph dev`` imports; ``env`` is where every
    credential on a live run comes from.
    """
    manifest = json.loads((REPO_ROOT / "langgraph.json").read_text(encoding="utf-8"))
    assert manifest.get("graphs"), "langgraph.json declares no graph to serve"
    assert manifest.get("env"), "langgraph.json no longer points at an env file"
