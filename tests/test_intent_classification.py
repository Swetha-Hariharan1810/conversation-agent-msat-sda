"""What kind of thing the member raised, and who decides it.

Four unrelated things arrive through one field. A member asking when somebody
will ring back about their bill, a member asking what a word in the question
means, a member asking us to post them a copy, and a member mentioning that
their daughter has arrived are not the same event, and the call owes each of
them something different: a line said out loud, the question put again, an entry
in the report a person works through, or nothing at all.

Deciding that from wording was never going to hold. The label arrives as free
text the model wrote — "wants to know about her claim" matched the keyword list
and "asked when someone will get back to her about the physio bill" did not — so
which of those two a member's unanswered bill produced was the model's choice of
phrasing, not anything the member said. It is asked of the model directly now,
and the wording is what is left for a remark the model did not label.

The cost of getting it wrong is one-sided, and the tests below are written round
that: a real request filed as chit-chat is dropped in silence, so an unlabelled
remark stays a request.
"""

from __future__ import annotations

import pytest

from msat_flow.agents.survey_agent import MsatSurveyAgent
from msat_flow.core.dialogue_manager import classify
from msat_flow.core.pending_intents import ACK_ONLY_KINDS, IntentKind, IntentStatus, PendingIntent
from msat_flow.llm.schema import SecondaryIntent, SecondaryIntentKind, TurnDecision
from msat_flow.script.spec import load_spec
from msat_flow.state import initial_state


@pytest.fixture(scope="module")
def spec():
    return load_spec()


@pytest.fixture
def agent(spec) -> MsatSurveyAgent:
    return MsatSurveyAgent(client=None, spec=spec)


def _raised(text: str, kind: SecondaryIntentKind = SecondaryIntentKind.UNSPECIFIED) -> SecondaryIntent:
    return SecondaryIntent(text=text, kind=kind)


def _kinds(agent: MsatSurveyAgent) -> list[str]:
    return [intent["kind"] for intent in agent._pending_intents]


# ── the model's answer decides ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("kind", "expected"),
    [
        (SecondaryIntentKind.MEMBER_SERVICES, IntentKind.UNSUPPORTED),
        (SecondaryIntentKind.REQUEST, IntentKind.SIDE_REQUEST),
        (SecondaryIntentKind.ABOUT_THE_SURVEY, IntentKind.CLARIFICATION),
        (SecondaryIntentKind.ASIDE, IntentKind.OFF_TOPIC),
    ],
)
def test_every_kind_the_model_can_say_reaches_the_ledger(kind, expected):
    """All four, and each one reachable.

    Two of the four branches used to be dead code: ``OFF_TOPIC`` was returned
    only for an empty label, which the caller skipped before ever calling, and
    ``CORRECTION`` only for a correction target the caller never passed. Every
    remark that was not one of ten keywords was therefore a side request.
    """
    assert classify(_raised("whatever they said", kind)) is expected


def test_the_paraphrase_the_keywords_missed():
    """The motivating turn.

    None of "claim", "billing", "invoice" or "payment" is in this sentence, and
    somebody is still waiting on an answer about a bill.
    """
    intent = _raised(
        "asked when someone will get back to her about the physio bill",
        SecondaryIntentKind.MEMBER_SERVICES,
    )

    assert classify(intent) is IntentKind.UNSUPPORTED


def test_a_remark_that_happens_to_contain_a_keyword_is_still_the_model_s_call():
    """The other direction. "The policy of calling in the evening" is not member
    services, and a keyword list has no way to know that. The model's answer
    wins over the wording, not the other way round."""
    intent = _raised("said our policy of ringing at teatime is a nuisance", SecondaryIntentKind.ASIDE)

    assert classify(intent) is IntentKind.OFF_TOPIC


# ── and the wording is what is left when it does not ─────────────────────


def test_an_unlabelled_remark_falls_back_to_the_wording():
    assert classify(_raised("wants to know about her claim")) is IntentKind.UNSUPPORTED


def test_an_unlabelled_remark_the_wording_cannot_place_is_a_request():
    """The safe way to be wrong: something a person looks at, rather than
    something dropped in silence."""
    assert classify(_raised("asked whether we ring everyone")) is IntentKind.SIDE_REQUEST


def test_a_bare_string_still_classifies():
    """The shape a model returns when it gives a phrase and no kind at all. It
    must take the fallback rather than fail the turn — a turn that cannot be read
    ends the call, which is a heavy price for a missing label on an aside."""
    assert classify("wants to know about her premium") is IntentKind.UNSUPPORTED
    assert classify("her daughter is visiting") is IntentKind.SIDE_REQUEST


# ── what capture does with them ──────────────────────────────────────────


def test_a_turn_that_raised_all_four_files_all_four(agent):
    agent.capture_and_triage(
        TurnDecision(
            secondary_intents=[
                _raised("when is somebody ringing back about the bill", SecondaryIntentKind.MEMBER_SERVICES),
                _raised("could you email me a copy", SecondaryIntentKind.REQUEST),
                _raised("what counts as a resource", SecondaryIntentKind.ABOUT_THE_SURVEY),
                _raised("her daughter has just arrived", SecondaryIntentKind.ASIDE),
            ]
        )
    )

    assert _kinds(agent) == [
        IntentKind.UNSUPPORTED.value,
        IntentKind.SIDE_REQUEST.value,
        IntentKind.CLARIFICATION.value,
        IntentKind.OFF_TOPIC.value,
    ]


def test_an_empty_phrase_is_still_dropped(agent):
    agent.capture_and_triage(TurnDecision(secondary_intents=[_raised("   ", SecondaryIntentKind.ASIDE)]))

    assert agent._pending_intents == []


def test_the_remark_is_kept_in_the_member_s_words(agent):
    agent.capture_and_triage(
        TurnDecision(secondary_intents=[_raised(" her daughter is visiting ", SecondaryIntentKind.ASIDE)])
    )

    assert agent._pending_intents[0]["raw_text"] == "her daughter is visiting"


# ── and what is said out loud about them ─────────────────────────────────


def test_only_member_services_draws_the_one_line_there_is(agent):
    """There is exactly one acknowledgement — "I'll note that and pass it on to
    the program team" — and it is a sentence about member services.

    Now that an aside can be produced at all, this is the check that stops it
    being answered with a promise nobody asked for. The member said their
    daughter had arrived.
    """
    assert ACK_ONLY_KINDS == frozenset({IntentKind.UNSUPPORTED.value})

    agent.capture_and_triage(
        TurnDecision(
            secondary_intents=[
                _raised("her daughter has just arrived", SecondaryIntentKind.ASIDE),
                _raised("what counts as a resource", SecondaryIntentKind.ABOUT_THE_SURVEY),
            ]
        )
    )

    assert not agent.side_request_ack(), "chit-chat was answered with the program-team line"


def test_member_services_does_draw_it(agent):
    agent.capture_and_triage(
        TurnDecision(
            secondary_intents=[
                _raised("when is somebody ringing back about the bill", SecondaryIntentKind.MEMBER_SERVICES)
            ]
        )
    )

    assert agent.side_request_ack() == agent.spec.policy.line("side_request_ack")
    assert not agent.side_request_ack(), "the line was said twice"


# ── the ledger is persisted state ────────────────────────────────────────


def test_a_ledger_written_before_this_change_still_loads(spec):
    """``_pending_intents`` survives a turn as plain dicts in graph state, so a
    call already in flight when this ships comes back with the old kinds on it.

    They are strings, and the new values are additions rather than replacements:
    nothing in the ledger reads a kind it does not know about, and the two that
    are still spelled the same still mean the same thing.
    """
    old = [
        {"kind": "unsupported", "raw_text": "when is my premium due?", "target": None, "status": "open"},
        {"kind": "side_request", "raw_text": "email me the results", "target": None, "status": "open"},
        {"kind": "off_topic", "raw_text": "her daughter is visiting", "target": None, "status": "open"},
        {
            "kind": "correction",
            "raw_text": "correct would_recommend",
            "target": "would_recommend",
            "status": "open",
        },
    ]
    state = {**initial_state({}), "pending_intents": old}

    agent = MsatSurveyAgent.from_state(state)

    assert agent._pending_intents == old
    assert agent.persisted()["pending_intents"] == old
    # The one that was owed a line is still owed it; the ones that were not,
    # still are not.
    assert agent.side_request_ack() == spec.policy.line("side_request_ack")
    assert [intent["status"] for intent in agent._pending_intents] == [
        IntentStatus.ACKNOWLEDGED.value,
        IntentStatus.OPEN.value,
        IntentStatus.OPEN.value,
        IntentStatus.OPEN.value,
    ]


def test_an_old_off_topic_intent_no_longer_takes_the_program_team_line(spec):
    """The one behaviour change a resumed call sees, and it is the point of the
    change: ``OFF_TOPIC`` was in ``ACK_ONLY_KINDS`` and could never be produced,
    so nothing was ever acknowledged under it in the first place."""
    state = {
        **initial_state({}),
        "pending_intents": [
            PendingIntent(kind=IntentKind.OFF_TOPIC.value, raw_text="her daughter is visiting").to_dict()
        ],
    }

    agent = MsatSurveyAgent.from_state(state)

    assert not agent.side_request_ack()
