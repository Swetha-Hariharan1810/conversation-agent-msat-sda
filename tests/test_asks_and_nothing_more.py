"""The predicate for a turn whose line is only the question.

``asks_and_nothing_more`` picks out the one turn where the generator has nothing
to do that a fixed line could not: a question the member has never been asked,
put in answer to a turn that held nothing but an answer. Every other turn is
asking it to bridge — to thank somebody, to read the options again, to pick a
question back up, to speak to something raised — and bridging is why it is there.

So the predicate is worth exactly as much as its false cases, and each one below
is a turn that must keep its generated line. Two of them look like duplicates and
are not:

* a ``SIDE_REQUEST`` raised **this** turn leaves the ack empty and is never
  spoken to, so only ``secondary_intents`` catches it;
* an ``UNSUPPORTED`` intent left open by an **earlier** turn is not in this
  turn's ``secondary_intents`` at all, so only the ledger catches it.

Collapse the two checks into one and one of those members is answered with a
fixed line and their request disappears without a word.

The last test is the mutation rule, and it is the reason the predicate reads the
ledger through ``open_intents`` rather than ``side_request_ack``: the latter
marks intents acknowledged as it answers, and a predicate that acknowledged
something would leave a remark marked as spoken to on a turn where nothing was
said about it.
"""

from __future__ import annotations

import pytest

from msat_flow.agents.survey_agent import MsatSurveyAgent
from msat_flow.core.pending_intents import IntentKind, IntentStatus, PendingIntent
from msat_flow.llm.schema import EventType, TurnDecision
from msat_flow.planner import Action, Plan
from msat_flow.script.spec import load_spec

SLOT = "reviewed_resources"


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture
def agent(spec) -> MsatSurveyAgent:
    return MsatSurveyAgent(client=None, spec=spec)


def _plan(action: Action = Action.ASK) -> Plan:
    return Plan(action=action, goal="ask whether they reviewed the resources", slots=(SLOT,))


def _answered(**overrides) -> TurnDecision:
    decision = TurnDecision(values={"would_recommend": "yes"}, event_type=EventType.ANSWERED)
    for name, value in overrides.items():
        setattr(decision, name, value)
    return decision


# A default that `None` can be passed past: "no decision at all" is one of the
# cases under test, so it cannot double as "use the ordinary one".
_UNSET = object()


def _ask(agent: MsatSurveyAgent, plan=None, decision=_UNSET, **overrides) -> bool:
    return agent.asks_and_nothing_more(
        plan or _plan(),
        _answered() if decision is _UNSET else decision,
        ask_counts=overrides.pop("ask_counts", {}),
        **overrides,
    )


# ── the one turn it is true for ──────────────────────────────────────────


def test_a_question_never_put_before_answering_a_plain_answer(agent):
    assert _ask(agent) is True


def test_a_question_no_one_has_counted_yet(agent):
    """An absent slot and a zero are the same thing — neither has been asked."""
    assert _ask(agent, ask_counts={"some_other_slot": 3}) is True


@pytest.mark.parametrize(
    "action", [Action.GREET, Action.ASK_CONSENT, Action.OFFER_RESCHEDULE, Action.ASK_RESCHEDULE_DATETIME]
)
def test_every_action_that_puts_a_question(agent, action):
    assert _ask(agent, plan=_plan(action)) is True


# ── and the turns it must not be ─────────────────────────────────────────


@pytest.mark.parametrize(
    "action",
    [Action.ACKNOWLEDGE_HOLD, Action.CLOSE, Action.LEAVE_VOICEMAIL, Action.HANDOFF_SAFEGUARDING],
)
def test_an_action_that_asks_nothing(agent, action):
    """Only a question can be a fixed question. A pause especially: "take your
    time" is said in the middle of a question the member is still thinking about,
    and it exists to be said in the agent's own words."""
    assert _ask(agent, plan=_plan(action)) is False


def test_a_question_that_has_been_put_before(agent):
    """Asked twice means there is a reason, and the member should hear it."""
    assert _ask(agent, ask_counts={SLOT: 1}) is False


def test_a_retry(agent):
    """A retry is the generator's whole job — say why it is being asked again."""
    assert _ask(agent, retry_slot=SLOT) is False


@pytest.mark.parametrize(
    "event",
    [
        # The one that matters most: they answered AND asked something back. The
        # answer is recorded either way, and the question they asked is only ever
        # answered by the line the generator composes.
        EventType.ANSWERED_WITH_REQUEST,
        EventType.CORRECTED,
        EventType.AMBIGUOUS,
        EventType.DECLINED,
        EventType.CLOSING,
    ],
)
def test_a_turn_that_was_not_a_plain_answer(agent, event):
    assert _ask(agent, decision=_answered(event_type=event)) is False


def test_a_turn_that_corrected_an_earlier_answer(agent):
    """They went back to fix something. Asking the next question as though they
    had not is the rudest thing on the call."""
    assert _ask(agent, decision=_answered(corrections={"would_recommend": "no"})) is False


def test_a_turn_that_raised_something_alongside_the_answer(agent):
    """The check that is not the ledger's.

    A ``SIDE_REQUEST`` is filed and never spoken to, so the ack is empty and the
    ledger's ack-only kinds do not see it. What answers it today is the generator
    getting the member's own words — so this turn must keep its generated line.
    """
    decision = _answered(secondary_intents=["can you send me a paper copy?"])
    agent.capture_and_triage(decision)

    kinds = {intent["kind"] for intent in agent._pending_intents}
    assert kinds == {IntentKind.SIDE_REQUEST.value}, (
        f"this test only means something if the intent is a side request, got {kinds}"
    )
    assert not agent.side_request_ack(), "a side request must leave the ack empty"

    assert _ask(agent, decision=decision) is False


def test_something_an_earlier_turn_raised_and_never_got_a_line(agent):
    """The check that is not ``secondary_intents``'.

    Owed from a previous turn, so nothing in *this* decision mentions it. The ack
    is waiting to be spoken and the line has to carry it.
    """
    agent._pending_intents = [
        PendingIntent(kind=IntentKind.UNSUPPORTED.value, raw_text="when is my premium due?").to_dict()
    ]
    assert _ask(agent) is False


def test_an_intent_already_spoken_to_is_no_longer_owed_a_line(agent):
    agent._pending_intents = [
        PendingIntent(
            kind=IntentKind.UNSUPPORTED.value,
            raw_text="when is my premium due?",
            status=IntentStatus.ACKNOWLEDGED.value,
        ).to_dict()
    ]
    assert _ask(agent) is True


def test_a_correction_on_the_ledger_does_not_by_itself_block_a_plain_ask(agent):
    """``ACK_ONLY_KINDS`` is ``UNSUPPORTED`` and ``OFF_TOPIC``, and nothing else.

    An open correction is answered by re-asking the question it belongs to, which
    the planner does; it is not owed a spoken acknowledgement, so it must not be
    read as one.
    """
    agent._pending_intents = [
        PendingIntent(
            kind=IntentKind.CORRECTION.value, raw_text="correct would_recommend", target="would_recommend"
        ).to_dict()
    ]
    assert _ask(agent) is True


def test_no_decision_at_all(agent):
    """The guard paths and the opening turn have nothing read. Not a plain ask."""
    assert _ask(agent, decision=None) is False


# ── and it changes nothing while deciding ────────────────────────────────


def test_the_predicate_never_marks_an_intent_acknowledged(agent):
    """The mutation rule, checked where it would actually go wrong.

    ``side_request_ack`` marks as it answers. If the predicate reached for it,
    this member's question about their premium would be recorded as spoken to on
    a turn where the agent said nothing about it — and the line that was owed
    would never be said, because the ledger no longer thinks it is owed.
    """
    owed = PendingIntent(kind=IntentKind.UNSUPPORTED.value, raw_text="when is my premium due?").to_dict()
    agent._pending_intents = [owed]

    for _ in range(3):
        assert _ask(agent) is False

    assert agent._pending_intents == [owed], "the predicate changed the intent ledger"
    assert agent.side_request_ack(), "the line that was owed can no longer be said"


def test_the_predicate_touches_nothing_else_either(agent):
    """No slot recorded, no attempt spent, no answer filed."""
    before = (dict(agent._answers), agent.slots_dict(), list(agent._pending_intents))

    assert _ask(agent) is True
    assert _ask(agent, decision=_answered(event_type=EventType.AMBIGUOUS)) is False

    assert (dict(agent._answers), agent.slots_dict(), list(agent._pending_intents)) == before
