"""Accessors for slot metadata, read from the compiled spec.

This module holds no table of its own. The document names the questions and
``data/slot_map.json`` says what kind of value each answer is, whether it counts
towards a complete survey, what its options are and how to describe it to the
extractor — so a new question needs no code change here, and a question with no
declaration fails the spec load rather than quietly becoming free text.
"""

from __future__ import annotations

from ..script.spec import Option, SlotSpec, SlotType, load_spec

__all__ = [
    "Option",
    "SlotSpec",
    "SlotType",
    "slot_spec",
    "slot_type",
    "is_critical",
    "describe",
    "options",
    "option_labels",
    "critical_slots",
]


def slot_spec(slot: str) -> SlotSpec:
    """The declaration for ``slot``. Raises SpecError if the script has no such slot."""
    return load_spec().slot(slot)


def slot_type(slot: str) -> SlotType:
    return slot_spec(slot).type


def is_critical(slot: str) -> bool:
    """Whether the answer counts towards a complete survey.

    Lenient on an unknown name: a slot the script does not define cannot gate an
    outcome. Genuine drift is caught at load by the spec validator.
    """
    declared = load_spec().slots.get(slot)
    return bool(declared and declared.critical)


def describe(slot: str) -> str:
    declared = load_spec().slots.get(slot)
    return declared.description if declared else slot.replace("_", " ")


def options(slot: str) -> tuple[Option, ...]:
    declared = load_spec().slots.get(slot)
    return declared.options if declared else ()


def option_labels(slot: str) -> tuple[str, ...]:
    return tuple(option.label for option in options(slot))


def critical_slots() -> frozenset[str]:
    return load_spec().critical_slots
