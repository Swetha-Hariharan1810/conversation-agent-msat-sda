"""The guard call and the extraction call go out together.

Both are put the same two things — what the caller last said and what the member
said back — and neither reads the other's answer, so asking them one after the
other made the member wait for the sum of two calls to be told one thing.

Running them together is only safe if it changes nothing else, and "nothing else"
is four separate promises, each of which this file holds to:

* **The guard still decides alone.** Every path the guard settles throws the
  reading away unlooked at — no slot recorded, no counter moved, no intent
  triaged — exactly as when the reading had not been started yet.
* **The error asymmetry survives.** A guard that cannot reach the provider
  degrades to patterns and the call goes on; a *reading* that fails ends the
  call. But a reading that fails on a turn the guard fires on is discarded with
  the rest, because ending a call over the extractor when the member asked for a
  person would be a regression the member pays for.
* **Nothing is launched that would not have run.** A date-and-time turn and a
  call with no model configured never reached the extractor, and still do not.
* **The first turn, and an empty one, are untouched.**

Timings come from ``msat_flow.llm.timing``, so "these two overlapped" is checked
against when the calls actually ran rather than against how long the turn took.
"""

from __future__ import annotations

import pytest

from msat_flow.agents.survey_agent import MsatSurveyAgent
from msat_flow.core import guards
from msat_flow.llm import timing
from msat_flow.llm.schema import EventType, GuardAssessment, TurnDecision
from msat_flow.script.spec import load_spec
from msat_flow.state import initial_state

from .doubles import Chat, provider
from .live.transcript import Exchange, _overlapping

PAYLOAD = {
    "workflow_subtype": "MEMBER_SATISFACTION_SURVEY",
    "call_context": {"call_id": "concurrency-test", "language": "en-US"},
    "policyholder": {"first_name": "Margaret", "last_name": "Ellison", "risk_tier": "high"},
}

# One delay for every role, so "these two overlapped" is a claim about when the
# calls ran rather than about which of them happened to be slower. Run in
# sequence a turn cannot finish inside 2 × DELAY.
DELAY = 0.05
DELAYS = dict.fromkeys(timing.ROLES, DELAY)

# A member turn that is a plain answer by the patterns' reckoning, so what the
# guard makes of it is entirely the scripted client's to decide.
PLAIN = "yes, a few of the articles"


def _state(member: str = PLAIN, *, awaiting: str = "reviewed_resources") -> dict:
    return {
        **initial_state(PAYLOAD),
        "messages": [{"role": "assistant", "content": "…"}, {"role": "user", "content": member}],
        "identity": "confirmed",
        "consent": "granted",
        "survey_started": True,
        "awaiting_slot": awaiting,
    }


@pytest.fixture(scope="module")
def spec():
    return load_spec()


def _chat(**scripted) -> Chat:
    """A provider whose every call takes the same time and answers what was asked.

    A fresh ``TurnDecision`` each time: the extractor filters the object it is
    handed, so two turns must not share one.
    """
    scripted.setdefault("decision", TurnDecision(values={"reviewed_resources": "yes"}))
    return Chat(delays=DELAYS, **scripted)


async def _run(spec, chat: Chat, state: dict | None = None):
    agent = MsatSurveyAgent(client=provider(chat), spec=spec)
    with timing.collecting() as timeline:
        result = await agent.run(state if state is not None else _state())
    return agent, result, timeline


# ── that they actually overlap ───────────────────────────────────────────


async def test_the_guard_call_and_the_reading_run_at_the_same_time(spec):
    _, _, timeline = await _run(spec, _chat())

    guard = next(call for call in timeline.calls if call.role == timing.GUARD)
    read = next(call for call in timeline.calls if call.role == timing.EXTRACT)
    assert guard.at < read.until and read.at < guard.until, (
        f"the two calls did not overlap: guard {guard.at:.3f}–{guard.until:.3f}, "
        f"extract {read.at:.3f}–{read.until:.3f}"
    )

    waited = timing.busy_seconds([guard, read])
    assert waited < guard.seconds + read.seconds, (
        "running them together must cost less than running them in sequence"
    )
    assert waited == pytest.approx(max(guard.seconds, read.seconds), abs=DELAY / 2), (
        f"two concurrent calls should cost about the longer of them, waited {waited:.3f}s"
    )


async def test_the_line_the_agent_speaks_still_waits_for_both(spec):
    """`generate` reads the planner's decision, so it cannot join the other two."""
    _, _, timeline = await _run(spec, _chat())

    spoken = next(call for call in timeline.calls if call.role == timing.GENERATE)
    read = next(call for call in timeline.calls if call.role == timing.EXTRACT)
    assert spoken.at >= read.until - 0.001, (
        "the agent started composing its line before it had finished reading the turn"
    )


# ── the guard still decides alone ────────────────────────────────────────


@pytest.mark.parametrize(
    ("field", "kind"),
    [
        ("safeguarding_concern", guards.SAFEGUARDING),
        ("asks_for_representative", guards.REPRESENTATIVE_REQUEST),
        ("voicemail_greeting", guards.VOICEMAIL),
        ("asks_to_hold", guards.HOLD),
        ("asks_not_to_be_called", guards.DO_NOT_CALL),
    ],
)
async def test_a_turn_the_guard_fires_on_is_never_read_as_survey_content(spec, field, kind):
    """The reading happened. It must be as though it had not.

    The scripted extractor returns a perfectly good answer to the outstanding
    question on every one of these turns; none of it may be recorded, and no
    counter may move on the strength of it.
    """
    chat = _chat(
        guard=GuardAssessment(**{field: True}),
        decision=TurnDecision(
            values={"reviewed_resources": "yes"},
            corrections={"would_recommend": "no"},
            event_type=EventType.ANSWERED,
        ),
    )
    agent, result, _ = await _run(spec, chat)

    assert timing.EXTRACT in chat.asked, "this test proves nothing if nothing was read"
    assert not agent.answer("reviewed_resources"), f"{kind}: the discarded reading was recorded"
    assert not agent.answer("would_recommend"), f"{kind}: a discarded correction was applied"
    assert not agent._answers, f"{kind}: {agent._answers} survived a guard turn"
    assert not agent._pending_intents, f"{kind}: the discarded turn was triaged"
    assert "declined" not in result, f"{kind}: a discarded reading touched declined"
    assert agent.slot("reviewed_resources").attempt_count == 0, (
        f"{kind}: a discarded reading spent a retry"
    )


async def test_a_hold_that_runs_out_ends_the_call_without_reading_the_turn(spec):
    """`HOLD_EXHAUSTED` is decided by the guard and the reading is discarded with it."""
    state = _state()
    state["ambiguous_counts"] = {"__holds__": spec.policy.max_consecutive_holds}
    agent, result, _ = await _run(spec, _chat(guard=GuardAssessment(asks_to_hold=True)), state)

    assert result["output_data"]["call_outcome"]["disposition"] == "ended_early"
    assert not agent._answers, "a turn that ran the holds out was still filed as an answer"


# ── the error asymmetry ──────────────────────────────────────────────────


async def test_a_reading_that_fails_still_ends_the_call(spec):
    """Unchanged: a turn we could not read is not a member being unclear."""
    agent, result, _ = await _run(spec, _chat(raises={timing.EXTRACT}))

    outcome = result["output_data"]["call_outcome"]
    assert outcome["disposition"] == "ended_early"
    assert "could not process the turn" in outcome["reason"], outcome["reason"]
    assert agent.slot("reviewed_resources").attempt_count == 0, "a failed reading burned a retry"


async def test_a_reading_that_fails_on_a_guard_turn_is_swallowed(spec):
    """The asymmetry that matters: the member gets the person, not a dropped call.

    Both calls are now in flight, so the extractor can fail on a turn that the
    guard fires on — which could not happen when it ran second. Ending the call
    over it would hang up on somebody who just asked for help.
    """
    chat = _chat(guard=GuardAssessment(asks_for_representative=True), raises={timing.EXTRACT})
    _, result, _ = await _run(spec, chat)

    outcome = result["output_data"]["call_outcome"]
    assert outcome["disposition"] == "representative_requested", (
        f"the reading's failure overrode the guard, got {outcome['disposition']!r}"
    )
    assert "could not process the turn" not in str(outcome), (
        "the discarded reading's exception reached the outcome"
    )


async def test_a_guard_call_that_fails_still_degrades_to_the_patterns(spec):
    """Unchanged, and the reading beside it is unaffected."""
    agent, result, _ = await _run(spec, _chat(raises={timing.GUARD}))

    assert agent.answer("reviewed_resources") == "yes", (
        "the guard falling back to patterns must not cost the turn its answer"
    )
    assert result.get("is_interrupt"), "a failed guard call ended the call"


async def test_a_guard_call_that_fails_on_a_safeguarding_turn_still_fires(spec):
    """The pattern floor holds with both calls in flight."""
    _, result, _ = await _run(
        spec, _chat(raises={timing.GUARD}), _state("I don't want to live any more")
    )

    assert result["output_data"]["call_outcome"]["disposition"] == "safeguarding_handoff"


# ── nothing is launched that would not have run ──────────────────────────


async def test_a_date_and_time_turn_never_reaches_the_extractor(spec):
    """Free text the call captures directly — no reading call, before or after."""
    chat = _chat()
    _, result, _ = await _run(spec, chat, _state("Thursday afternoon", awaiting="reschedule_datetime"))

    assert timing.EXTRACT not in chat.asked, (
        f"the concurrent path launched a call the sequential one never made: {chat.asked}"
    )
    assert result.get("reschedule_datetime") == "Thursday afternoon"


async def test_no_model_configured_reads_the_turn_without_a_call(spec):
    agent = MsatSurveyAgent(client=None, spec=spec)
    with timing.collecting() as timeline:
        await agent.run(_state())

    assert not timeline.calls, "the offline path made a provider call"
    assert agent.answer("reviewed_resources") == "yes"


async def test_the_first_turn_of_the_call_reads_nothing(spec):
    """No member text at all: the agent just opens."""
    chat = _chat()
    state = {**initial_state(PAYLOAD), "messages": []}
    result = await MsatSurveyAgent(client=provider(chat), spec=spec).run(state)

    assert chat.asked == [timing.GENERATE], f"the opening turn made {chat.asked}"
    assert result.get("is_interrupt")


async def test_a_whitespace_turn_is_read_but_trips_no_guard(spec):
    """Unchanged: the guard short-circuits on blank text, the reading still runs."""
    chat = _chat(decision=TurnDecision())
    _, result, _ = await _run(spec, chat, _state("   "))

    assert timing.GUARD not in chat.asked, "a blank turn was put to the guard model"
    assert timing.EXTRACT in chat.asked, "a blank turn was no longer read"
    assert result.get("is_interrupt"), "a blank turn ended the call"


# ── the arithmetic behind the reports ────────────────────────────────────


def test_overlapping_calls_are_counted_once_in_what_was_waited_for():
    calls = [
        timing.Call(timing.GUARD, 0.4, at=0.0),
        timing.Call(timing.EXTRACT, 0.9, at=0.05),
        timing.Call(timing.GENERATE, 0.5, at=1.2),
    ]
    # 0.0–0.95 then 1.2–1.7: 0.95 + 0.5, against 1.8s of provider time.
    assert timing.busy_seconds(calls) == pytest.approx(1.45)
    assert sum(call.seconds for call in calls) == pytest.approx(1.8)


@pytest.mark.parametrize(
    ("spans", "together"),
    [
        ([(timing.GUARD, 0.0, 0.4), (timing.EXTRACT, 0.0, 0.9)], "guard + extract"),
        # One call handing straight over to the next is consecutive, not
        # concurrent. Reported as overlap it would credit the concurrency with a
        # saving it did not make.
        ([(timing.EXTRACT, 0.0, 0.9), (timing.GENERATE, 0.9, 2.1)], ""),
        ([(timing.EXTRACT, 0.0, 0.9), (timing.GENERATE, 0.8999, 2.1)], ""),
        ([(timing.GUARD, 0.0, 0.4)], ""),
        ([], ""),
    ],
)
def test_the_transcript_only_claims_calls_ran_together_when_they_did(spans, together):
    exchange = Exchange(
        scenario="x",
        caller="",
        member="",
        calls=[
            timing.Call(role, end - start, at=start).as_dict() for role, start, end in spans
        ],
    )
    assert _overlapping(exchange) == together


@pytest.mark.parametrize(
    ("spans", "expected"),
    [
        ([], 0.0),
        ([(0.0, 1.0)], 1.0),
        ([(0.0, 1.0), (2.0, 3.0)], 2.0),  # disjoint
        ([(0.0, 1.0), (0.5, 2.0)], 2.0),  # overlapping
        ([(0.0, 2.0), (0.5, 1.0)], 2.0),  # wholly contained
        ([(1.0, 2.0), (0.0, 0.5)], 1.5),  # out of order
    ],
)
def test_busy_seconds_takes_the_union_of_the_spans(spans, expected):
    calls = [timing.Call("x", end - start, at=start) for start, end in spans]
    assert timing.busy_seconds(calls) == pytest.approx(expected)
