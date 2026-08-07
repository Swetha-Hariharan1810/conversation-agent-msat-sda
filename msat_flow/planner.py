"""The self-directing planner.

Every turn, this decides what the agent does next from the *state of the call*
rather than from a position in the script. A member can answer two questions in
one breath, take the third question as an invitation to tell a story, or come
back to question one after question four, and the next action still falls out of
"what does this member still owe us, and are we still allowed to ask?".

Precedence, highest first:

  1. we reached an answering machine — leave the message and stop
  2. we did not reach the policyholder — say so and stop
  3. establish we are speaking to the policyholder
  4. get consent to ask the questions
  5. if consent is refused, offer to reschedule, then act on the answer
  6. open the survey
  7. put the next applicable unanswered question, in the document's order
  8. close

Nothing here hard-codes a question, an option or a condition — the spec supplies
all three. The one thing the planner *does* own is the order of those seven
beats, because that order is the call rather than the questionnaire.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable

from .core.guards import HOLD as GUARD_HOLD
from .core.guards import REPRESENTATIVE_REQUEST as GUARD_REPRESENTATIVE
from .core.guards import SAFEGUARDING as GUARD_SAFEGUARDING
from .core.guards import VOICEMAIL as GUARD_VOICEMAIL
from .script.spec import SurveySpec, Turn


class Action(StrEnum):
    HANDOFF_SAFEGUARDING = "handoff_safeguarding"
    HANDOFF_REPRESENTATIVE = "handoff_representative"
    LEAVE_VOICEMAIL = "leave_voicemail"
    ACKNOWLEDGE_HOLD = "acknowledge_hold"
    END_UNAVAILABLE = "end_unavailable"
    END_WRONG_NUMBER = "end_wrong_number"
    GREET = "greet"
    ASK_CONSENT = "ask_consent"
    OFFER_RESCHEDULE = "offer_reschedule"
    TRANSFER_RESCHEDULE = "transfer_reschedule"
    ASK_RESCHEDULE_DATETIME = "ask_reschedule_datetime"
    CLOSE_RESCHEDULE = "close_reschedule"
    END_UNINTERESTED = "end_uninterested"
    ASK = "ask"
    CLOSE = "close"


# Actions that leave a question hanging, so ``awaiting_slot`` must point at it.
QUESTION_ACTIONS = frozenset(
    {Action.GREET, Action.ASK_CONSENT, Action.OFFER_RESCHEDULE, Action.ASK_RESCHEDULE_DATETIME, Action.ASK}
)
# Actions that end the call the moment they are spoken.
FINAL_ACTIONS = frozenset(
    {
        Action.HANDOFF_SAFEGUARDING,
        Action.HANDOFF_REPRESENTATIVE,
        Action.LEAVE_VOICEMAIL,
        Action.END_UNAVAILABLE,
        Action.END_WRONG_NUMBER,
        Action.TRANSFER_RESCHEDULE,
        Action.CLOSE_RESCHEDULE,
        Action.END_UNINTERESTED,
        Action.CLOSE,
    }
)
# Actions that hand the call to a human rather than ending it.
TRANSFER_ACTIONS = frozenset(
    {Action.HANDOFF_SAFEGUARDING, Action.HANDOFF_REPRESENTATIVE, Action.TRANSFER_RESCHEDULE}
)
# Actions that say something without asking anything, so the question already
# outstanding stays outstanding. Acknowledging a pause must not lose the
# question the member is pausing to think about.
PRESERVE_AWAITING = frozenset({Action.ACKNOWLEDGE_HOLD})

# Identity readings the member's turn can settle.
IDENTITY_CONFIRMED = "confirmed"
IDENTITY_UNAVAILABLE = "unavailable"
IDENTITY_WRONG_NUMBER = "wrong_number"
CONSENT_GRANTED = "granted"
CONSENT_DECLINED = "declined"


@dataclass(frozen=True)
class Plan:
    action: Action
    goal: str
    node: str = ""
    text: str = ""
    slots: tuple[str, ...] = ()
    # Option labels to read aloud, exactly as the document prints them.
    options: tuple[str, ...] = ()
    # Values this turn may speak from the work item.
    values: dict[str, str] = field(default_factory=dict)
    # Say ``text`` exactly. True for the voicemail, the closing and every
    # off-script line: those are approved wording, not an intent to paraphrase.
    verbatim: bool = False
    # Said immediately before this turn, in the same breath. The document's
    # "Great. Let's get started..." is a lead-in rather than a question, and
    # saying it on its own would leave the agent waiting for a reply to nothing.
    preamble: str = ""
    preamble_node: str = ""

    @property
    def slot(self) -> str:
        return self.slots[0] if self.slots else ""


@dataclass(frozen=True)
class Skipped:
    slot: str
    node: str
    reason: str


def _turn_plan(
    action: Action,
    turn: Turn,
    *,
    values: dict[str, str] | None = None,
    verbatim: bool = False,
    preamble: Turn | None = None,
) -> Plan:
    return Plan(
        action=action,
        goal=turn.goal,
        node=turn.node,
        preamble=preamble.text if preamble is not None else "",
        preamble_node=preamble.node if preamble is not None else "",
        # One turn in the document prints the wrong question — see the source
        # note on 1b. Where the spec says so, the goal is what gets spoken and
        # the printed text is not offered to the generator at all.
        text="" if turn.speak_goal_not_text else turn.text,
        slots=turn.slots,
        options=turn.options,
        values=dict(values or {}),
        verbatim=verbatim,
    )


def _off_script(spec: SurveySpec, action: Action, name: str) -> Plan:
    """A line the document does not contain, spoken as ``slot_map.json`` declares.

    Verbatim unless that line carries a goal, which only the courtesies do — see
    ``SpokenLine``. Nothing about *what happens to the member* is paraphrased.
    """
    spoken = spec.policy.spoken(name)
    return Plan(action=action, goal=spoken.goal, text=spoken.line, verbatim=spoken.verbatim)


def applies(turn: Turn, *, answers: dict[str, str], payload_lookup: Callable[[str], str]) -> bool:
    """Whether this member should be asked ``turn`` at all."""
    return turn.when is None or turn.when.holds(answers=answers, payload_lookup=payload_lookup)


def applicable_questions(
    spec: SurveySpec, *, answers: dict[str, str], payload_lookup: Callable[[str], str]
) -> tuple[Turn, ...]:
    return tuple(
        turn for turn in spec.questions if applies(turn, answers=answers, payload_lookup=payload_lookup)
    )


def skipped_questions(
    spec: SurveySpec, *, answers: dict[str, str], payload_lookup: Callable[[str], str]
) -> tuple[Skipped, ...]:
    """Questions this member's script ruled out, and what ruled them out.

    Reported rather than silently absent. "No answer to question 5" and "question
    5 does not apply to a rising-risk policyholder" are different facts, and only
    one of them is a gap in the data.
    """
    return tuple(
        Skipped(slot=turn.slot, node=turn.node, reason=turn.when.describe())
        for turn in spec.questions
        if turn.when is not None and not applies(turn, answers=answers, payload_lookup=payload_lookup)
    )


def outstanding_questions(
    spec: SurveySpec,
    *,
    answers: dict[str, str],
    declined: tuple[str, ...] | list[str],
    payload_lookup: Callable[[str], str],
) -> list[str]:
    """Applicable questions with no answer that the member did not decline."""
    settled = set(declined or ())
    return [
        turn.slot
        for turn in applicable_questions(spec, answers=answers, payload_lookup=payload_lookup)
        if turn.slot and not answers.get(turn.slot) and turn.slot not in settled
    ]


def plan_next(
    spec: SurveySpec,
    *,
    answers: dict[str, str],
    declined: tuple[str, ...] | list[str] = (),
    identity: str = "",
    consent: str = "",
    reschedule: str = "",
    reschedule_datetime: str = "",
    survey_started: bool = False,
    guard: str = "",
    payload_lookup: Callable[[str], str],
) -> Plan:
    """Choose this turn's action. Pure function of call state — easy to test.

    ``guard`` is whatever the member's turn raised before any of it was read as
    an answer. It outranks the whole call, and its own order matters: somebody
    who is not safe gets a person before anything else is considered.
    """

    # 0. Safety, and then the member's own request for a human. Neither is a
    #    survey question and neither may ever be re-asked.
    if guard == GUARD_SAFEGUARDING:
        return _off_script(spec, Action.HANDOFF_SAFEGUARDING, "safeguarding_handoff")
    if guard == GUARD_REPRESENTATIVE:
        return _off_script(spec, Action.HANDOFF_REPRESENTATIVE, "representative_handoff")

    # 1. An answering machine. Leave the message the document wrote for it and
    #    stop; there is nobody to ask anything of.
    if guard == GUARD_VOICEMAIL:
        return _turn_plan(Action.LEAVE_VOICEMAIL, spec.of_kind("voicemail"), verbatim=True)

    # 2. They need a moment. Say so and wait — the question stays outstanding.
    if guard == GUARD_HOLD:
        return _off_script(spec, Action.ACKNOWLEDGE_HOLD, "hold_ack")

    # 3. Whoever answered, it is not the policyholder and will not be today.
    #    The document does not cover this, so the wording is declared off-script.
    if identity == IDENTITY_UNAVAILABLE:
        return _off_script(spec, Action.END_UNAVAILABLE, "policyholder_unavailable")
    if identity == IDENTITY_WRONG_NUMBER:
        return _off_script(spec, Action.END_WRONG_NUMBER, "wrong_number")

    # 3. Ask for the policyholder by name. Until they confirm, there is nobody
    #    whose satisfaction we could be recording.
    if identity != IDENTITY_CONFIRMED:
        greeting = spec.of_kind("intro")
        # The document's greeting has a placeholder for the name. A work item
        # that did not supply one still has to be greeted — asking for "the
        # policyholder" is honest, and reading the placeholder out loud is the
        # one thing that must not happen.
        stand_in = spec.policy.line("unnamed_policyholder")
        return _turn_plan(
            Action.GREET,
            greeting,
            values={slot: payload_lookup(slot) or stand_in for slot in greeting.payload_slots},
        )

    # 4-5. Consent, and the reschedule branch the document draws behind it.
    if consent != CONSENT_GRANTED:
        if consent != CONSENT_DECLINED:
            return _turn_plan(Action.ASK_CONSENT, spec.of_kind("consent"))
        if not reschedule:
            return _turn_plan(Action.OFFER_RESCHEDULE, spec.of_kind("reschedule_offer"), verbatim=True)
        if reschedule == "yes":
            if not reschedule_datetime:
                spoken = spec.policy.spoken("reschedule_datetime_ask")
                return Plan(
                    action=Action.ASK_RESCHEDULE_DATETIME,
                    text=spoken.line,
                    goal=spoken.goal,
                    verbatim=spoken.verbatim,
                    slots=("reschedule_datetime",),
                )
            return _off_script(spec, Action.CLOSE_RESCHEDULE, "reschedule_datetime_confirm")
        return _turn_plan(Action.END_UNINTERESTED, spec.of_kind("uninterested_close"), verbatim=True)

    # 6-7. The next question that applies to this member and is still open.
    #      Order is the document's; applicability is the condition's. A question
    #      already answered out of turn is skipped without comment, which is
    #      what lets a member volunteer three answers at once.
    #
    #      The first question carries the survey's opening line with it. The
    #      document draws that line as its own beat, but it asks for nothing —
    #      speaking it alone would leave the agent waiting on a reply to a
    #      statement, and the member waiting for a question that never came.
    preamble = None if survey_started else spec.of_kind("survey_intro")
    settled = set(declined or ())
    for turn in applicable_questions(spec, answers=answers, payload_lookup=payload_lookup):
        if not turn.slots:
            continue
        if all(answers.get(slot) or slot in settled for slot in turn.slots):
            continue
        return _turn_plan(Action.ASK, turn, preamble=preamble)

    # 8. Done.
    return _turn_plan(Action.CLOSE, spec.of_kind("close"), verbatim=True, preamble=preamble)
