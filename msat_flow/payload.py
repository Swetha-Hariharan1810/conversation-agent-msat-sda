"""Read work-item values out of the inbound payload.

Two things come from the work item and nothing else does: the policyholder's name,
which the introduction speaks, and the risk tier, which decides whether question 5
is asked. Where each lives is declared in ``data/slot_map.json`` under ``payload``
and checked against ``data/input_schema.json`` when the spec loads, so a binding
that names a field the schema does not declare is a build failure rather than an
empty string on a live call.
test check
Nothing is found by searching. A survey that guesses a risk tier asks a question
of the wrong member and files the answer as if it had been asked correctly.
"""

from __future__ import annotations

from typing import Any

from .script.spec import SurveySpec


def _read(data: dict[str, Any], path: str) -> str:
    """Read one dotted path. Missing, null and empty all read as absent."""
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict):
            return ""
        node = node.get(part)
        if node is None:
            return ""
    if isinstance(node, (dict, list)):
        return ""
    return str(node).strip()


def resolve(spec: SurveySpec, data: dict[str, Any] | None, slot: str) -> str:
    """The payload's value for ``slot``, or "" if the work item does not carry it.

    Declared paths are tried in order. ``compose`` is the one construction we
    allow — joining fields the payload actually supplied — and only when no
    single declared path holds a value.
    """
    binding = spec.payload.get(slot)
    if binding is None or not data:
        return ""

    for path in binding.paths:
        value = _read(data, path)
        if value:
            return value

    if binding.compose:
        parts = [_read(data, path) for path in binding.compose]
        if all(parts):
            return " ".join(parts)
    return ""


def missing_required(data: dict[str, Any] | None, schema: dict[str, Any]) -> list[str]:
    """Required sections and fields the work item does not carry, dotted-path.

    Mirrors the RCM platform contract: the caller reports missing required fields
    rather than starting a call it cannot complete.
    """
    if not isinstance(data, dict):
        return list(schema.get("required") or [])
    missing: list[str] = []
    properties = schema.get("properties") or {}
    for section in schema.get("required") or []:
        value = data.get(section)
        if value is None or value == "":
            missing.append(section)
            continue
        section_schema = properties.get(section) or {}
        if section_schema.get("type") != "object" or not isinstance(value, dict):
            continue
        for field in section_schema.get("required") or []:
            if not str(value.get(field) or "").strip():
                missing.append(f"{section}.{field}")
    return missing
