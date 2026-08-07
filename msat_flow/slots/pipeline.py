"""Normalise → validate → record, for one slot.

The single place a member-stated answer becomes a recorded one, so the agent, the
planner and the tests all agree on what "answered" means.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..script.spec import SlotSpec, SlotType
from .normalizers import normalize
from .types import slot_spec
from .validators import validate


def _no_match_reason(declared: SlotSpec) -> str:
    if declared.type is SlotType.CHOICE:
        return f"it matched none of the options ({', '.join(declared.option_labels)})"
    return "nothing usable in the answer"


@dataclass(frozen=True)
class SlotResult:
    slot: str
    value: str
    accepted: bool
    reason: str = ""


def accept(slot: str, raw: str) -> SlotResult:
    """Try to record ``raw`` as the answer to ``slot``.

    Nothing that fails validation is kept, whatever the slot's criticality. An
    unvalidated choice answer is not a weaker version of an answer — it is a
    rating the member did not give.
    """
    declared = slot_spec(slot)
    value = normalize(declared, raw or "")
    if not value:
        # The reason travels into the re-ask, so on a choice question it says
        # what the options were. "I didn't catch that" invites the member to
        # repeat the same unusable phrase; hearing the four ratings again is
        # what actually gets an answer.
        return SlotResult(slot, "", False, _no_match_reason(declared))

    result = validate(declared, value)
    if result.valid:
        return SlotResult(slot, value, True)
    return SlotResult(slot, "", False, result.reason)
