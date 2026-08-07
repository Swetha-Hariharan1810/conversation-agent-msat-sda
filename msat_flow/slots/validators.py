"""Validators, one per slot type.

A validator runs on an already-normalised value and decides whether it is safe to
record. Nothing that fails is stored: on a survey a missing answer is honest and
a wrong one is not, and the question can simply be asked again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..script.spec import SlotSpec, SlotType
from .normalizers import NO_FEEDBACK_VALUE

MIN_FEEDBACK_CHARS = 3


@dataclass(frozen=True)
class Result:
    valid: bool
    reason: str = ""

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.valid


OK = Result(True)


def _fail(reason: str) -> Result:
    return Result(False, reason)


def validate_yes_no(value: str) -> Result:
    return OK if value in ("yes", "no") else _fail("not a yes or no")


def validate_choice(value: str, declared: SlotSpec) -> Result:
    """The recorded value must be one of the options the document prints.

    The normaliser is the only thing that produces these, so a failure here means
    the extractor invented an option — exactly the case where storing it would
    put a rating in the results that the member never chose.
    """
    if value in declared.option_values:
        return OK
    return _fail(f"not one of the options ({', '.join(declared.option_labels)})")


def validate_feedback_text(value: str) -> Result:
    if value == NO_FEEDBACK_VALUE:
        return OK
    if len((value or "").strip()) < MIN_FEEDBACK_CHARS:
        return _fail("too short to be an answer")
    return OK


def validate_person_name(value: str) -> Result:
    return OK if re.fullmatch(r"[A-Za-z'\-]+(?: [A-Za-z'\-]+)*", value or "") else _fail("not a name")


def validate(declared: SlotSpec, value: str) -> Result:
    if declared.type is SlotType.YES_NO:
        return validate_yes_no(value)
    if declared.type is SlotType.CHOICE:
        return validate_choice(value, declared)
    if declared.type is SlotType.FEEDBACK_TEXT:
        return validate_feedback_text(value)
    if declared.type is SlotType.PERSON_NAME:
        return validate_person_name(value)
    raise ValueError(f"no validator for slot type {declared.type!r}")  # pragma: no cover
