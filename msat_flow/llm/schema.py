"""Structured result of reading one member turn."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EventType(StrEnum):
    ANSWERED = "ANSWERED"  # gave us an answer to something
    ANSWERED_WITH_REQUEST = "ANSWERED_WITH_REQUEST"  # answered and asked something back
    CORRECTED = "CORRECTED"  # revised an answer already given
    AMBIGUOUS = "AMBIGUOUS"  # said something, but no usable answer
    DECLINED = "DECLINED"  # will not answer this question
    CLOSING = "CLOSING"  # winding the call down


class IdentityDetail(StrEnum):
    """Why the person on the line is not the policyholder.

    Only read when ``reached_policyholder`` came back "no". The distinction is
    the difference between a work item worth retrying tomorrow and a phone
    number that should never be dialled for this member again.
    """

    NONE = ""
    UNAVAILABLE = "unavailable"  # right household, wrong person, or they cannot come to the phone
    WRONG_NUMBER = "wrong_number"  # no such person here


class TurnDecision(BaseModel):
    """What the member's latest turn contained.

    Extraction is deliberately literal: ``values`` may only hold things the
    member actually said. The prompt forbids inference, every answer is
    normalised and validated afterwards, and a choice that does not match one of
    the printed options is dropped rather than recorded.
    """

    event_type: EventType = Field(default=EventType.ANSWERED)
    values: dict[str, str] = Field(
        default_factory=dict, description="slot name -> the answer, in the member's own words"
    )
    corrections: dict[str, str] = Field(
        default_factory=dict, description="slot name -> revised answer, when the member changed one"
    )
    secondary_intents: list[str] = Field(
        default_factory=list, description="anything else the member raised in the same turn"
    )
    identity_detail: IdentityDetail = Field(
        default=IdentityDetail.NONE,
        description="only when the policyholder was not reached: unavailable, or wrong_number",
    )
    declines_question: bool = Field(
        default=False, description="true when the member would rather not answer what was just asked"
    )
    safeguarding_concern: bool = Field(
        default=False,
        description=(
            "true when anything they said suggests they may be at risk — harm to themselves, "
            "harm or neglect by someone else, or a medical emergency. Err towards true."
        ),
    )
    asks_for_representative: bool = Field(
        default=False, description="true when they asked to be put through to a person"
    )
