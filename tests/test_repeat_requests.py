"""What a question back costs the member.

"Sorry, could you say that again?" is not a failed attempt at the question. It
is a member who has not been asked it yet in terms they could answer. But it
arrives at ``_retry_target`` looking like any other turn that settled nothing,
and what happens there decides three separate things:

* whether the slot's **retry budget** is charged, which at three ends with the
  question filed under ``declined`` — reported to the business as somebody who
  would rather not say, about somebody who was trying to answer;
* whether the question goes out **again at all**;
* what the next line **says**, because the reason travels into
  ``speak_line.retry.md`` and decides whether Ida apologises for mishearing when
  it was the member who did not hear.

The turns are driven through the whole agent with a scripted extractor, so what
is asserted is the accounting the agent actually does rather than a call to the
predicate in isolation.
"""

from __future__ import annotations

import pytest

from msat_flow.agents.survey_agent import MsatSurveyAgent
from msat_flow.llm import timing
from msat_flow.llm.schema import (
    EventType,
    GuardAssessment,
    SecondaryIntent,
    SecondaryIntentKind,
    TurnDecision,
)
from msat_flow.script.spec import load_spec
from msat_flow.state import initial_state

from .doubles import Chat, provider

SLOT = "reviewed_resources"

PAYLOAD = {
    "workflow_subtype": "MEMBER_SATISFACTION_SURVEY",
    "call_context": {"call_id": "repeat-test", "language": "en-US"},
    "policyholder": {"first_name": "Margaret", "last_name": "Ellison", "risk_tier": "high"},
}

REPEAT = "Sorry, could you say that again?"


@pytest.fixture(scope="module")
def spec():
    return load_spec()


def _state(*, awaiting: str = SLOT, member: str = REPEAT) -> dict:
    return {
        **initial_state(PAYLOAD),
        "messages": [
            {"role": "assistant", "content": "Were you able to review any of the program resources?"},
            {"role": "user", "content": member},
        ],
        "identity": "confirmed",
        "consent": "granted",
        "survey_started": True,
        "awaiting_slot": awaiting,
    }


def _asks_back(**overrides) -> TurnDecision:
    """A turn that asked us something and answered nothing."""
    decision = TurnDecision(
        event_type=EventType.ANSWERED_WITH_REQUEST,
        secondary_intents=[
            SecondaryIntent(
                text="asked us to repeat the question", kind=SecondaryIntentKind.ABOUT_THE_SURVEY
            )
        ],
    )
    for name, value in overrides.items():
        setattr(decision, name, value)
    return decision


async def _turn(spec, decision: TurnDecision, state: dict | None = None):
    """One turn through the real agent, with the extractor scripted."""
    chat = Chat(delays={role: 0.0 for role in timing.ROLES}, guard=GuardAssessment(), decision=decision)
    agent = MsatSurveyAgent(client=provider(chat), spec=spec)
    result = await agent.run(state if state is not None else _state())
    return agent, result, chat


# ── the budget ───────────────────────────────────────────────────────────


async def test_a_repeat_request_does_not_spend_an_attempt(spec):
    agent, result, _ = await _turn(spec, _asks_back())

    assert agent.slot(SLOT).attempt_count == 0, (
        "a member who could not hear the question was charged with failing to answer it"
    )
    assert result.get("awaiting_slot") == SLOT, "the question was not put again"
    assert not agent.answer(SLOT), "nothing was said, so nothing may be recorded"
    assert not result.get("declined"), "a question back was settled as a refusal"


async def test_the_ask_count_still_moves(spec):
    """Unchanged on purpose. Putting the question again IS another ask, and the
    backstop in ``run`` that counts them is what stops a question going out for
    ever. Only the retry budget is what a question back must not spend."""
    agent, result, _ = await _turn(spec, _asks_back())

    assert result.get("ask_counts", {}).get(SLOT) == 1


async def test_three_repeats_in_a_row_still_leave_the_question_open(spec):
    """The case the whole change is for.

    Read as unclear answers these three exhaust ``max_asks_per_slot`` and the
    question is filed under declined. Read as what they are, the member is still
    being asked.
    """
    state = _state()
    for _ in range(3):
        agent, update, _ = await _turn(spec, _asks_back(), state)
        state = {
            **state,
            **update,
            "messages": [*state["messages"], *(update.get("messages") or [])],
        }
        state["messages"] = [*state["messages"], {"role": "user", "content": REPEAT}]

    assert agent.slot(SLOT).attempt_count == 0
    assert SLOT not in (state.get("declined") or []), (
        "three repeat requests filed the question as one the member would rather not answer"
    )
    assert state.get("awaiting_slot") == SLOT, "the agent stopped asking"


async def test_an_unclear_answer_still_spends_one(spec):
    """The other side of the branch. A reply that went at the question and missed
    is a failed attempt, and must stay one — the budget exists for exactly this."""
    agent, _, _ = await _turn(
        spec, TurnDecision(event_type=EventType.AMBIGUOUS), _state(member="Oh, I don't know really.")
    )

    assert agent.slot(SLOT).attempt_count == 1


async def test_an_answer_with_nothing_in_it_still_spends_one(spec):
    agent, _, _ = await _turn(spec, TurnDecision(event_type=EventType.ANSWERED))

    assert agent.slot(SLOT).attempt_count == 1


# ── what the next line is told ───────────────────────────────────────────


async def test_the_reason_says_what_actually_happened(spec):
    """The reason renders into ``speak_line.retry.md``.

    "The answer was unclear" makes Ida say she did not catch something when it
    was the member who did not — an apology in the wrong direction, to somebody
    who has just asked her to speak up.
    """
    _, _, chat = await _turn(spec, _asks_back())

    spoken = chat.sent(timing.GENERATE)[-1]
    assert "asked us something back" in spoken, spoken
    assert "the answer was unclear" not in spoken, (
        "the retry context still blames the member for an answer they did not give"
    )
    assert "no answer was given" not in spoken, spoken


async def test_the_question_goes_out_with_retry_context_at_all(spec):
    """Before this branch existed the turn fell through to ``None``.

    The question was still re-asked — the planner wants it until it is answered —
    but with no ``retry_slot``, so the retry section never rendered and the line
    was composed as though the question were being put for the first time.
    """
    _, _, chat = await _turn(spec, _asks_back())

    spoken = chat.sent(timing.GENERATE)[-1]
    assert "Ask again" in spoken, "the retry wording was never sent to the generator"
    assert "Attempt 0" not in spoken, "the attempt counter was rendered from an unspent budget"


# ── ordering against the branches around it ──────────────────────────────


async def test_declining_and_asking_in_one_breath_is_settled_not_retried(spec):
    """"I'd rather not, and who did you say you were with?" — the refusal wins.

    Re-asking would talk over an answer the member has already given about the
    survey itself.
    """
    agent, result, _ = await _turn(spec, _asks_back(declines_question=True))

    assert SLOT in (result.get("declined") or []), "a refusal was retried instead of settled"
    assert agent.slot(SLOT).attempt_count == 0


async def test_an_answer_the_slot_rejected_keeps_its_own_reason(spec):
    """They asked something back AND gave something the slot would not take.

    The rejection is a real failed attempt with a more specific reason, and it
    must win — otherwise an unusable rating rides in behind a question back and
    never counts against anything.
    """
    decision = _asks_back(values={SLOT: "somewhere in the middle"})
    agent, _, chat = await _turn(spec, decision, _state(awaiting="overall_experience"))

    assert "asked us something back" not in chat.sent(timing.GENERATE)[-1]


async def test_a_correction_alongside_a_question_back_still_gets_the_context(spec):
    """The branch sits ahead of the corrections check.

    A member who fixes an earlier answer and asks us something in the same turn
    needs the next line to deal with what they asked. Neither spends the budget,
    so putting this first costs nothing and says more.
    """
    decision = _asks_back(corrections={"would_recommend": "no"})
    agent, _, chat = await _turn(spec, decision)

    assert agent.slot(SLOT).attempt_count == 0
    assert "asked us something back" in chat.sent(timing.GENERATE)[-1]
