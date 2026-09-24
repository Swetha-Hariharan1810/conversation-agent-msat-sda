"""Turning an incoming work item into what one call needs.

The work item is the only input a call gets::

    {
      "workflow_subtype": "MEMBER_SATISFACTION_SURVEY",
      "member_id": "ABC_TMJarrett",
      "prepop": {"FirstName": "Jarrett", "DOB": "2010-01-06", ...}
    }

``member_id`` becomes Expert24's ``@UserID``; ``prepop`` is checked against the
survey's declared fields and sent as ``Prepop``. Values are checked, never
rewritten: Expert24 receives exactly what the work item carried, plus any
declared defaults. Every problem is reported at once, so a bad work item is
fixed in one round rather than one field at a time.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .definition import ExtraFields, FieldType, PrepopField, SurveyDefinition


class WorkItemError(ValueError):
    def __init__(self, workflow_subtype: str, problems: list[str]) -> None:
        super().__init__(f"{workflow_subtype}: " + "; ".join(problems))
        self.workflow_subtype = workflow_subtype
        self.problems = problems


class CallContext(BaseModel):
    """Everything about this call that came from outside it."""

    model_config = ConfigDict(frozen=True)

    survey: SurveyDefinition
    member_id: str
    prepop: dict[str, Any]
    speak_values: dict[str, Any] = Field(default_factory=dict)

    def lookup(self, path: str) -> Any:
        return lookup(path, {"member_id": self.member_id, "prepop": self.prepop})


_MISSING = object()


def lookup(path: str, data: Mapping[str, Any]) -> Any:
    """Resolve a dotted path such as ``prepop.FirstName``; None when absent."""
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, Mapping):
            return None
        node = node.get(part, _MISSING)
        if node is _MISSING:
            return None
    return node


def _is_iso_date(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 10:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _check(name: str, value: Any, spec: PrepopField) -> str | None:
    if spec.type is FieldType.STRING and not isinstance(value, str):
        return f"prepop.{name} must be a string"
    if spec.type is FieldType.DATE and not _is_iso_date(value):
        return f"prepop.{name} must be a date as YYYY-MM-DD; got {value!r}"
    if spec.type is FieldType.INTEGER and (isinstance(value, bool) or not isinstance(value, int)):
        return f"prepop.{name} must be an integer"
    if spec.type is FieldType.NUMBER and (
        isinstance(value, bool) or not isinstance(value, int | float)
    ):
        return f"prepop.{name} must be a number"
    if spec.type is FieldType.BOOLEAN and not isinstance(value, bool):
        return f"prepop.{name} must be true or false"
    if spec.choices is not None and str(value) not in spec.choices:
        return f"prepop.{name} must be one of {', '.join(spec.choices)}; got {value!r}"
    return None


def prepare(survey: SurveyDefinition, work_item: Mapping[str, Any]) -> CallContext:
    problems: list[str] = []

    member_id = work_item.get("member_id")
    if not isinstance(member_id, str) or not member_id.strip():
        problems.append("member_id is required")

    raw_prepop = work_item.get("prepop") or {}
    if not isinstance(raw_prepop, Mapping):
        problems.append("prepop must be an object")
        raw_prepop = {}

    prepop: dict[str, Any] = {}
    for name, spec in survey.prepop.fields.items():
        value = raw_prepop.get(name)
        if value is None or value == "":
            if spec.default is not None:
                prepop[name] = spec.default
            elif spec.required:
                problems.append(f"prepop.{name} is required")
            continue
        if problem := _check(name, value, spec):
            problems.append(problem)
        prepop[name] = value

    extra = sorted(set(raw_prepop) - set(survey.prepop.fields))
    if extra and survey.prepop.extra is ExtraFields.FORBID:
        problems.append(f"prepop has undeclared fields: {', '.join(extra)}")
    for name in extra:
        prepop[name] = raw_prepop[name]

    if problems:
        raise WorkItemError(survey.workflow_subtype, problems)

    assert isinstance(member_id, str)
    data = {"member_id": member_id, "prepop": prepop}
    return CallContext(
        survey=survey,
        member_id=member_id,
        prepop=prepop,
        speak_values={key: lookup(path, data) for key, path in survey.speak_values.items()},
    )
