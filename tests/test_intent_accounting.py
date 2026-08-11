"""What closes each thing the member raised, and what is left open.

The ledger is only worth as much as the entries that are still on it at the end
of the call, and until now nothing ever came off. A member who asked us to say
the question again had that filed as a request; the caller said the question
again on the very next breath, and the request stayed open for the rest of the
call and was reported to the business as something nobody dealt with. So did a
remark about their daughter visiting. On an eldercare satisfaction survey those
are most calls, and they are what the one real entry — somebody waiting on a
claim — was buried under.

Each kind has a closing event, and they are different events:

* a **clarification** is closed by the question going out again, which is the
  answer to it;
* an **aside** is closed the moment it is heard, because nothing is owed;
* a **correction** is closed by the corrected answer being recorded;
* **member services** is closed by the line said about it — and a **side
  request** by nothing here at all, which is exactly what it is for.

The turns are driven through the whole agent rather than through the ledger
functions, because what is under test is when the agent calls them.
"""

from __future__ import annotations

import pytest

from msat_flow.agents.survey_agent import MsatSurveyAgent
from msat_flow.core.pending_intents import IntentKind, IntentStatus
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
    "call_context": {"call_id": "accounting-test", "language": "en-US"},
    "policyholder": {"first_name": "Margaret", "last_name": "Ellison", "risk_tier": "high"},
}


@pytest.fixture(scope="module")
def spec():
    return load_spec()


def _state(*, awaiting: str = SLOT, member: str = "What counts as a resource, exactly?") -> dict:
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


def _raised(text: str, kind: SecondaryIntentKind) -> SecondaryIntent:
    return SecondaryIntent(text=text, kind=kind)


async def _turn(spec, decision: TurnDecision, state: dict | None = None):
    """One turn through the real agent, with the extractor scripted."""
    chat = Chat(delays={role: 0.0 for role in timing.ROLES}, guard=GuardAssessment(), decision=decision)
    agent = MsatSurveyAgent(client=provider(chat), spec=spec)
    result = await agent.run(state if state is not None else _state())
    return agent, result, chat


async def _resumed(spec, state: dict, decision: TurnDecision, guard: GuardAssessment | None = None):
    """A later turn of the same call, rebuilt from state the way the graph does.

    ``app_graph`` builds the agent with ``from_state`` every turn, so the ledger
    arrives as the plain dicts it was persisted as. Anything asserted here is
    therefore asserted about state that went through a checkpoint.
    """
    chat = Chat(
        delays={role: 0.0 for role in timing.ROLES},
        guard=guard if guard is not None else GuardAssessment(),
        decision=decision,
    )
    agent = MsatSurveyAgent.from_state(state)
    agent.client = provider(chat)
    agent.spec = spec
    return agent, await agent.run(state), chat


def _ledger(agent: MsatSurveyAgent) -> list[tuple[str, str]]:
    return [(intent["kind"], intent["status"]) for intent in agent._pending_intents]


def _still_open(result: dict) -> list[dict]:
    return [intent for intent in result["pending_intents"] if intent["status"] == IntentStatus.OPEN.value]


# ── a question about the question ────────────────────────────────────────


async def test_the_question_going_out_again_closes_it(spec):
    """The turn this exists for. They asked what a word meant; the caller reads
    the question out again on this very turn, so nothing is outstanding."""
    agent, result, _ = await _turn(
        spec,
        TurnDecision(
            event_type=EventType.ANSWERED_WITH_REQUEST,
            secondary_intents=[_raised("what counts as a resource", SecondaryIntentKind.ABOUT_THE_SURVEY)],
        ),
    )

    assert result.get("awaiting_slot") == SLOT, "the question was not put again"
    assert _ledger(agent) == [(IntentKind.CLARIFICATION.value, IntentStatus.RESOLVED.value)]
    assert not _still_open(result), "a question answered on the same turn was reported as outstanding"


async def test_asking_to_hear_it_again_is_the_same_thing(spec):
    agent, result, _ = await _turn(
        spec,
        TurnDecision(
            event_type=EventType.ANSWERED_WITH_REQUEST,
            secondary_intents=[
                _raised("asked us to repeat the question", SecondaryIntentKind.ABOUT_THE_SURVEY)
            ],
        ),
        _state(member="Sorry, could you say that again?"),
    )

    assert not _still_open(result)
    assert agent.slot(SLOT).attempt_count == 0, "closing the request charged the member for it"


async def test_three_of_them_do_not_pile_up(spec):
    """Each is closed by the turn that answers it, so the ledger does not grow a
    queue of the same unanswered question."""
    state = _state()
    for _ in range(3):
        decision = TurnDecision(
            event_type=EventType.ANSWERED_WITH_REQUEST,
            secondary_intents=[
                _raised("asked us to repeat the question", SecondaryIntentKind.ABOUT_THE_SURVEY)
            ],
        )
        agent, update, _ = await _turn(spec, decision, state)
        state = {**state, **update, "messages": [*state["messages"], *(update.get("messages") or [])]}
        state["messages"] = [*state["messages"], {"role": "user", "content": "Sorry, again?"}]

    assert not _still_open(state)
    assert {status for _, status in _ledger(agent)} == {IntentStatus.RESOLVED.value}


async def test_one_asked_alongside_an_answer_stays_open(spec):
    """The other side of the rule, and the reason it is drawn where it is.

    They answered, so the call moves on to the next question and nothing is read
    back to them. Their question went unanswered on this turn, and the report
    should say so rather than claim the caller dealt with it.
    """
    agent, result, _ = await _turn(
        spec,
        TurnDecision(
            event_type=EventType.ANSWERED_WITH_REQUEST,
            values={SLOT: "yes"},
            secondary_intents=[
                _raised("does that include the calls with my coach", SecondaryIntentKind.ABOUT_THE_SURVEY)
            ],
        ),
    )

    assert agent.answer(SLOT) == "yes", "the answer was lost"
    assert result.get("awaiting_slot") != SLOT, "the call did not move on"
    assert _ledger(agent) == [(IntentKind.CLARIFICATION.value, IntentStatus.OPEN.value)]


# ── an aside ─────────────────────────────────────────────────────────────


async def test_an_aside_is_kept_and_owed_nothing(spec):
    agent, result, chat = await _turn(
        spec,
        TurnDecision(
            values={SLOT: "yes"},
            secondary_intents=[_raised("her daughter has just arrived", SecondaryIntentKind.ASIDE)],
        ),
    )

    assert _ledger(agent) == [(IntentKind.OFF_TOPIC.value, IntentStatus.NOTED.value)]
    assert agent._pending_intents[0]["raw_text"] == "her daughter has just arrived"
    assert not _still_open(result), "chit-chat was reported as an unresolved member request"
    assert "pass it on to the program team" not in chat.sent(timing.GENERATE)[-1], (
        "the member was promised the program team would hear that her daughter had arrived"
    )


# ── the two that are meant to survive the call ───────────────────────────


async def test_member_services_is_acknowledged_out_loud(spec):
    agent, _, chat = await _turn(
        spec,
        TurnDecision(
            values={SLOT: "yes"},
            secondary_intents=[
                _raised(
                    "asked when someone will get back to her about the physio bill",
                    SecondaryIntentKind.MEMBER_SERVICES,
                )
            ],
        ),
    )

    assert _ledger(agent) == [(IntentKind.UNSUPPORTED.value, IntentStatus.ACKNOWLEDGED.value)]
    assert "pass it on to the program team" in chat.sent(timing.GENERATE)[-1], (
        "the one line there is for member services was never said"
    )


async def test_a_side_request_is_closed_by_nothing_here(spec):
    """No line, no closing event: it leaves the call still open, for a person to
    pick up. That is what the reported list is for, and it only means anything
    now that the asides and the answered questions are not in it."""
    _, result, _ = await _turn(
        spec,
        TurnDecision(
            values={SLOT: "yes"},
            secondary_intents=[_raised("could you email me a copy", SecondaryIntentKind.REQUEST)],
        ),
    )

    assert [intent["kind"] for intent in _still_open(result)] == [IntentKind.SIDE_REQUEST.value]


async def test_a_whole_turn_of_everything_at_once(spec):
    """All four in one breath, which is the turn the old classifier flattened
    into four identical side requests.

    Every one is dealt with differently on the turn itself: the bill is spoken
    to, the question is put again, the aside is simply heard, and the one thing
    nobody on this call can do is left open. What of that reaches the report is
    the section below.
    """
    agent, result, _ = await _turn(
        spec,
        TurnDecision(
            event_type=EventType.ANSWERED_WITH_REQUEST,
            secondary_intents=[
                _raised("when is somebody ringing back about the bill", SecondaryIntentKind.MEMBER_SERVICES),
                _raised("could you email me a copy", SecondaryIntentKind.REQUEST),
                _raised("what counts as a resource", SecondaryIntentKind.ABOUT_THE_SURVEY),
                _raised("her daughter has just arrived", SecondaryIntentKind.ASIDE),
            ],
        ),
    )

    assert _ledger(agent) == [
        (IntentKind.UNSUPPORTED.value, IntentStatus.ACKNOWLEDGED.value),
        (IntentKind.SIDE_REQUEST.value, IntentStatus.OPEN.value),
        (IntentKind.CLARIFICATION.value, IntentStatus.RESOLVED.value),
        (IntentKind.OFF_TOPIC.value, IntentStatus.NOTED.value),
    ]
    assert [intent["kind"] for intent in _still_open(result)] == [IntentKind.SIDE_REQUEST.value]


# ── and what the call reports at the end ─────────────────────────────────


def _everything_at_once() -> TurnDecision:
    return TurnDecision(
        event_type=EventType.ANSWERED_WITH_REQUEST,
        secondary_intents=[
            _raised("when is somebody ringing back about the bill", SecondaryIntentKind.MEMBER_SERVICES),
            _raised("could you email me a copy", SecondaryIntentKind.REQUEST),
            _raised("what counts as a resource", SecondaryIntentKind.ABOUT_THE_SURVEY),
            _raised("her daughter has just arrived", SecondaryIntentKind.ASIDE),
        ],
    )


async def _closed_after(spec, decision: TurnDecision) -> dict:
    """Raise something on one turn, end the call on the next, return the outcome.

    The call is ended by the member asking not to be called again, which is a
    guard: it settles the turn without reading it, so the second turn adds
    nothing to the ledger and what comes out is what the first turn left.
    """
    _, first, _ = await _turn(spec, decision)
    resumed = {
        **_state(),
        **first,
        "messages": [
            *_state()["messages"],
            *(first.get("messages") or []),
            {"role": "user", "content": "Take me off your list, would you."},
        ],
    }
    _, ended, _ = await _resumed(
        spec, resumed, TurnDecision(), guard=GuardAssessment(asks_not_to_be_called=True)
    )
    return ended["output_data"]["call_outcome"]


async def test_the_report_holds_what_still_needs_somebody(spec):
    """The whole point of the change, read where a person reads it.

    Before: four entries, all "side_request", three of them noise — the request,
    a question the caller answered thirty seconds later, and a member's daughter
    arriving. The one that mattered was in there somewhere.

    After: the bill and the request. Nothing else.
    """
    outcome = await _closed_after(spec, _everything_at_once())

    assert [(intent["kind"], intent["raw_text"]) for intent in outcome["open_intents"]] == [
        (IntentKind.UNSUPPORTED.value, "when is somebody ringing back about the bill"),
        (IntentKind.SIDE_REQUEST.value, "could you email me a copy"),
    ]


async def test_the_promise_to_pass_it_on_is_not_the_passing_on(spec):
    """The acknowledged entry is the load-bearing one.

    "I'll note that and pass it on to the program team" is a promise, and this
    list is where it gets kept. Reporting only OPEN intents would have dropped
    every member-services request at the moment the caller promised to pass it
    on — emptying the report of precisely the category with consequences.
    """
    outcome = await _closed_after(
        spec,
        TurnDecision(
            values={SLOT: "yes"},
            secondary_intents=[
                _raised("has her new card come through yet", SecondaryIntentKind.MEMBER_SERVICES)
            ],
        ),
    )

    assert [intent["status"] for intent in outcome["open_intents"]] == [IntentStatus.ACKNOWLEDGED.value]


async def test_a_call_of_nothing_but_chat_reports_nothing(spec):
    """The eldercare call this is really about: warm, talkative, and asking us
    for nothing. It used to end with a list of unresolved member requests."""
    outcome = await _closed_after(
        spec,
        TurnDecision(
            values={SLOT: "yes"},
            secondary_intents=[
                _raised("her daughter visits on Thursdays", SecondaryIntentKind.ASIDE),
                _raised("it has been raining all week", SecondaryIntentKind.ASIDE),
            ],
        ),
    )

    assert outcome["open_intents"] == []
