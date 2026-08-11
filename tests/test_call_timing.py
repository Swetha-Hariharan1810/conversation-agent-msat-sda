"""Per-role timing of the three model calls a turn makes.

The instrumentation is only worth anything if three things hold, and each is
easy to break without noticing:

* **A turn's calls are labelled.** A turn makes up to three provider calls, and
  a total that does not say which was which cannot tell you what to fix. So the
  guard call must arrive labelled ``guard``, the extraction call ``extract`` and
  the spoken line ``generate`` — through the real agent and the real client, not
  through a hand-made call to ``measure``.
* **Failures are timed too.** A provider timeout is the slowest thing a turn can
  do, and a table that drops those looks its best exactly when the call went
  its worst.
* **Nothing is measured when nobody is collecting.** This sits in the path of
  every provider call on a live call, so with no collector it must record
  nothing at all.

The real ``LLMClient`` runs throughout, with a fake chat model where the network
would be — a sleep per role, each a different length, which is how these can tell
that a label follows the call that produced it. So the whole file runs on every
``pytest``, needs no credentials and costs nothing.
"""

from __future__ import annotations

import json

import pytest

from msat_flow.agents.survey_agent import MsatSurveyAgent
from msat_flow.llm import timing
from msat_flow.llm.client import LLMClient
from msat_flow.script.spec import load_spec
from msat_flow.state import initial_state

from .doubles import DELAYS, Chat, provider

# Aliased on import: pytest collects anything named Test* in a test module, and
# this one is a recorder, not a test case.
from .live.transcript import Conversation, Recorder
from .live.transcript import TestTranscript as Transcript

PAYLOAD = {
    "workflow_subtype": "MEMBER_SATISFACTION_SURVEY",
    "call_context": {"call_id": "timing-test", "language": "en-US"},
    "policyholder": {"first_name": "Margaret", "last_name": "Ellison", "risk_tier": "high"},
}

GUARD_DELAY = DELAYS[timing.GUARD]
GENERATE_DELAY = DELAYS[timing.GENERATE]


def _state(member: str, *, awaiting: str) -> dict:
    return {
        **initial_state(PAYLOAD),
        "messages": [{"role": "assistant", "content": "…"}, {"role": "user", "content": member}],
        "identity": "confirmed",
        "consent": "granted",
        "survey_started": True,
        "awaiting_slot": awaiting,
    }


async def _turn(spec, client: LLMClient) -> dict:
    return await MsatSurveyAgent(client=client, spec=spec).run(
        _state("yes, a few of the articles", awaiting="reviewed_resources")
    )


@pytest.fixture(scope="module")
def spec():
    return load_spec()


async def test_a_turn_reports_each_of_its_three_calls_under_its_own_role(spec):
    client = provider(Chat())
    with timing.collecting() as timeline:
        await _turn(spec, client)

    assert sorted(call.role for call in timeline.calls) == sorted(timing.ROLES), (
        "every call a turn makes must arrive under its own role; a total that cannot "
        "say which call it was cannot say what to fix"
    )

    took = {call.role: call.seconds for call in timeline.calls}
    assert took[timing.GENERATE] > took[timing.EXTRACT] > took[timing.GUARD], (
        f"each call's time must follow the call it timed, got {took}"
    )
    assert all(call.ok for call in timeline.calls)


async def test_a_failed_call_is_still_timed(spec):
    """Dropping failures would flatter exactly the turns that went worst."""
    with timing.collecting() as timeline:
        await _turn(spec, provider(Chat(raises={timing.GUARD})))

    guard = next(call for call in timeline.calls if call.role == timing.GUARD)
    assert not guard.ok, "a call that raised was recorded as though it had worked"
    assert guard.seconds >= GUARD_DELAY, "a failed call must carry the time it burned before failing"


async def test_nothing_is_measured_when_nobody_is_collecting(spec):
    """The guarantee that lets this sit in the path of every call on a live one."""
    client = provider(Chat())
    await _turn(spec, client)

    assert timing.active() is None, "a collector outlived the block that installed it"
    assert len(client._chat.asked) == 3, "the turn made no calls at all; this test would prove nothing"


async def test_collecting_stops_at_the_end_of_its_block(spec):
    with timing.collecting() as timeline:
        await _turn(spec, provider(Chat()))
    before = len(timeline)

    with timing.collecting():
        await _turn(spec, provider(Chat()))

    assert len(timeline) == before, "a later turn's calls landed on a closed timeline"


# ── what the transcript makes of them ────────────────────────────────────


async def test_the_transcript_attributes_each_turns_calls_to_that_turn(spec):
    """Two turns, and each exchange carries only the calls it made.

    This is what makes a transcript actionable rather than merely timed: the
    per-turn number says the turn was slow, and the calls beside it say which of
    the three the member was waiting on.
    """
    conversation = Conversation(test="tests/live/test_x.py::test_two_turns")
    with timing.collecting() as timeline:
        handle = Transcript(conversation, timeline)
        for _ in range(2):
            await _turn(spec, provider(Chat()))
            handle.exchange(scenario="two_turns", member="yes, a few of the articles")

    assert [len(exchange.calls) for exchange in conversation.exchanges] == [3, 3], (
        "each turn must carry its own three calls, not the running total"
    )
    # Sorted, not in order: two of the three calls run concurrently now, so which
    # of them is recorded first is a race and asserting on it would be flaky.
    assert all(
        sorted(call["role"] for call in exchange.calls) == sorted(timing.ROLES)
        for exchange in conversation.exchanges
    )
    first = conversation.exchanges[0]
    # Overlap counted once, so what was waited for is strictly below what the
    # provider spent: the guard call runs inside the reading's wait.
    assert 0 < first.waiting_s < first.calls_s, "the concurrent calls were counted as sequential"


async def test_the_run_ends_with_a_per_role_baseline(spec, tmp_path, monkeypatch):
    """A run must leave behind the table this whole exercise is for."""
    monkeypatch.setattr("tests.live.transcript.RESULTS_DIR", tmp_path)
    recorder = Recorder()
    recorder.context = {"provider": "scripted", "model": "none"}

    node = "tests/live/test_x.py::test_a_call"
    with timing.collecting() as timeline:
        handle = Transcript(recorder.conversation(node), timeline)
        await _turn(spec, provider(Chat()))
        handle.exchange(scenario="a_call", member="yes, a few of the articles")

    written = recorder.complete(node, "passed")
    directory = recorder.finish()

    transcript = written.read_text(encoding="utf-8")
    assert "share of turn time" in transcript, "a transcript must say where its time went, by role"
    assert "- calls: guard" in transcript, "each turn must list the calls it made"

    index = (directory / "index.md").read_text(encoding="utf-8")
    assert "## Latency baseline" in index
    for role in timing.ROLES:
        assert f"| {role} |" in index, f"{role} is missing from the run's baseline table"

    baseline = json.loads((directory / "baseline.json").read_text(encoding="utf-8"))
    assert baseline["calls"] == 3
    assert set(baseline["roles"]) == set(timing.ROLES)
    assert baseline["roles"][timing.GENERATE]["p95_s"] >= GENERATE_DELAY
    assert 0 < baseline["roles"][timing.GENERATE]["share_of_turn_time"] <= 1

    assert "generate p50" in recorder.headline()


# ── the arithmetic ───────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("values", "share", "expected"),
    [
        ([1.0], 0.50, 1.0),
        ([1.0], 0.95, 1.0),
        ([1.0, 2.0, 3.0, 4.0], 0.50, 2.0),
        ([1.0, 2.0, 3.0, 4.0], 0.95, 4.0),
        ([4.0, 1.0, 3.0, 2.0], 0.50, 2.0),  # unsorted input
        ([], 0.50, 0.0),
    ],
)
def test_percentiles_report_a_time_that_actually_happened(values, share, expected):
    """Nearest-rank, so every figure in the table is a real duration.

    At the sample sizes a live run produces — tens of calls — an interpolated p95
    would invent a number between two real ones and read as better evidence than
    it is.
    """
    assert timing.percentile(values, share) == expected


def test_a_role_that_made_no_calls_is_absent_rather_than_zero():
    """A run that never reached the extractor should say so by the gap.

    A row of zeroes reads like a call that was fast, which is the opposite of
    what happened.
    """
    stats = timing.summarise([timing.Call(timing.GUARD, 0.5), timing.Call(timing.GUARD, 1.5)])
    assert set(stats) == {timing.GUARD}
    assert stats[timing.GUARD].count == 2
    assert stats[timing.GUARD].total_s == 2.0
