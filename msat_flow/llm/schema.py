"""Structured results the model returns about one member turn.

Two of them, asked for separately and in this order: ``GuardAssessment`` decides
whether the turn is something the survey cannot carry on through, and only if it
is not does ``TurnDecision`` read the turn as an answer.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EventType(StrEnum):
    """What kind of turn this was.

    ANSWERED: they answered something we asked.
    ANSWERED_WITH_REQUEST: they said something to us that needs a reply — a
    question of their own, or asking us to say the question again. This covers
    "sorry, could you repeat that?", "what do you mean by resources?" and "does
    that include the calls with my coach?", whether or not they also answered.
    CORRECTED: they revised an answer they had already given.
    AMBIGUOUS: they tried to answer the question but what they said cannot be
    mapped to a value.
    DECLINED: they will not answer this question.
    CLOSING: they are winding the call down.

    The line that matters most is between the second and the fourth. A member
    asking us to repeat the question, or asking what a word in it means, has not
    failed to answer it — they have not been asked it yet in terms they could
    answer. AMBIGUOUS is for a reply that went at the question and missed.
    """

    ANSWERED = "ANSWERED"
    ANSWERED_WITH_REQUEST = "ANSWERED_WITH_REQUEST"
    CORRECTED = "CORRECTED"
    AMBIGUOUS = "AMBIGUOUS"
    DECLINED = "DECLINED"
    CLOSING = "CLOSING"


class IdentityDetail(StrEnum):
    """Why the person on the line is not the policyholder.

    Only read when ``reached_policyholder`` came back "no". The distinction is
    the difference between a work item worth retrying tomorrow and a phone
    number that should never be dialled for this member again.
    """

    NONE = ""
    UNAVAILABLE = "unavailable"  # right household, wrong person, or they cannot come to the phone
    WRONG_NUMBER = "wrong_number"  # no such person here


class GuardAssessment(BaseModel):
    """Whether one member turn is something the survey cannot carry on through.

    Five independent judgements rather than a single label, because a turn can be
    more than one of them at once: "just put me through to somebody, and take me
    off your list" is a request for a person *and* a request to stop calling.
    Which one wins is not asked of the model — the precedence is written down in
    ``core/guards.py``, where it can be read and tested.

    Every field defaults to false. A model that returns nothing at all therefore
    says "ordinary turn", which is both the common case and the safe one: the
    survey carries on and the extractor still reads the turn.
    """

    safeguarding_concern: bool = Field(
        default=False,
        description=(
            "true when anything they said suggests they may be at risk — harm to themselves, "
            "harm or neglect by someone else, or a medical emergency. Err towards true."
        ),
    )
    asks_for_representative: bool = Field(
        default=False, description="true when they asked to be put through to a person, now"
    )
    voicemail_greeting: bool = Field(
        default=False,
        description=(
            "true when this is a recorded greeting — an answering machine or a voicemail "
            "service — rather than a person"
        ),
    )
    asks_not_to_be_called: bool = Field(
        default=False,
        description=(
            "true when they want the calls to stop altogether. Declining this survey, or asking "
            "to be called back another time, is not this."
        ),
    )
    asks_to_hold: bool = Field(
        default=False,
        description="true when they are stepping away for a moment and mean to come back",
    )


class TurnDecision(BaseModel):
    """What the member's latest turn contained.

    Extraction is deliberately literal: ``values`` may only hold things the
    member actually said. The prompt forbids inference, every answer is
    normalised and validated afterwards, and a choice that does not match one of
    the printed options is dropped rather than recorded.
    """

    event_type: EventType = Field(
        default=EventType.ANSWERED,
        description=(
            "what kind of turn this was. ANSWERED: they answered something. "
            "ANSWERED_WITH_REQUEST: they asked us something back, including asking us to say "
            "the question again or to explain a word in it — use this whether or not they also "
            "answered. CORRECTED: they revised an earlier answer. AMBIGUOUS: they went at the "
            "question and what they said cannot be mapped to a value. DECLINED: they will not "
            "answer it. CLOSING: they are ending the call. Asking us to repeat the question is "
            "ANSWERED_WITH_REQUEST, never AMBIGUOUS: they have not failed to answer it."
        ),
    )
    values: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "slot name -> the answer, in the member's own words. Only what they said out loud "
            "this turn. Empty when they asked us something instead of answering."
        ),
    )
    corrections: dict[str, str] = Field(
        default_factory=dict, description="slot name -> revised answer, when the member changed one"
    )
    secondary_intents: list[str] = Field(
        default_factory=list,
        description=(
            "anything else they raised in the same turn — a question for us, a request, a "
            "complaint. One short phrase each. A request to repeat the question goes here too."
        ),
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
