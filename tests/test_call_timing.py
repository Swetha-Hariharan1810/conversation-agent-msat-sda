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

import asyncio
import json

import pytest

from msat_flow.agents.survey_agent import MsatSurveyAgent
from msat_flow.llm import timing
from msat_flow.llm.client import LLMClient
from msat_flow.llm.schema import GuardAssessment, TurnDecision
from msat_flow.script.spec import load_spec
from msat_flow.state import initial_state

# Aliased on import: pytest collects anything named Test* in a test module, and
# this one is a recorder, not a test case.
from .live.transcript import Conversation, Recorder
from .live.transcript import TestTranscript as Transcript

PAYLOAD = {
    "workflow_subtype": "MEMBER_SATISFACTION_SURVEY",
    "call_context": {"call_id": "timing-test", "language": "en-US"},
    "policyholder": {"first_name": "Margaret", "last_name": "Ellison", "risk_tier": "high"},
}

# Long enough to measure, short enough that the suite does not notice. They
# differ from each other on purpose: that is what proves a timing's label follows
# the call it timed rather than the order the calls happened to be made in.
GUARD_DELAY = 0.01
EXTRACT_DELAY = 0.02
GENERATE_DELAY = 0.04


class Spoken:
    """What a chat model returns from ``ainvoke`` — content and nothing else."""

    def __init__(self, content: str) -> None:
        self.content = content


class StructuredChain:
    """What ``with_structured_output`` returns: a chain that answers in a schema."""

    def __init__(self, chat, schema) -> None:
        self._chat = chat
        self._schema = schema

    async def ainvoke(self, messages):
        self._chat.calls += 1
        if self._chat.fails:
            await asyncio.sleep(GUARD_DELAY)
            raise RuntimeError("provider unavailable")
        if self._schema is GuardAssessment:
            await asyncio.sleep(GUARD_DELAY)
            return GuardAssessment()
        await asyncio.sleep(EXTRACT_DELAY)
        return TurnDecision(values={"reviewed_resources": "yes"})


class SlowChat:
    """A chat model that answers correctly, each kind of call taking its own time.

    Stands exactly where ``langchain_openai``'s does, so the client's own code —
    including the clock around it — is the code under test.
    """

    def __init__(self, fails: bool = False) -> None:
        self.calls = 0
        self.fails = fails

    def with_structured_output(self, schema, method: str = ""):
        return StructuredChain(self, schema)

    async def ainvoke(self, messages):
        self.calls += 1
        await asyncio.sleep(GENERATE_DELAY)
        return Spoken("And how helpful were they?")


def _client(fails: bool = False) -> LLMClient:
    """The real client, with the provider replaced and nothing else."""
    client = LLMClient()
    client._chat = SlowChat(fails=fails)
    return client


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
    client = _client()
    with timing.collecting() as timeline:
        await _turn(spec, client)

    assert [call.role for call in timeline.calls] == [timing.GUARD, timing.EXTRACT, timing.GENERATE], (
        "a turn's calls must arrive labelled and in order — guard first, because a "
        "member who is not safe is never made to wait on the survey reading their turn"
    )

    took = {call.role: call.seconds for call in timeline.calls}
    assert took[timing.GENERATE] > took[timing.EXTRACT] > took[timing.GUARD], (
        f"each call's time must follow the call it timed, got {took}"
    )
    assert all(call.ok for call in timeline.calls)


async def test_a_failed_call_is_still_timed(spec):
    """Dropping failures would flatter exactly the turns that went worst."""
    with timing.collecting() as timeline:
        await _turn(spec, _client(fails=True))

    guard = next(call for call in timeline.calls if call.role == timing.GUARD)
    assert not guard.ok, "a call that raised was recorded as though it had worked"
    assert guard.seconds >= GUARD_DELAY, "a failed call must carry the time it burned before failing"


async def test_nothing_is_measured_when_nobody_is_collecting(spec):
    """The guarantee that lets this sit in the path of every call on a live one."""
    client = _client()
    await _turn(spec, client)

    assert timing.active() is None, "a collector outlived the block that installed it"
    assert client._chat.calls == 3, "the turn made no calls at all; this test would prove nothing"


async def test_collecting_stops_at_the_end_of_its_block(spec):
    with timing.collecting() as timeline:
        await _turn(spec, _client())
    before = len(timeline)

    with timing.collecting():
        await _turn(spec, _client())

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
            await _turn(spec, _client())
            handle.exchange(scenario="two_turns", member="yes, a few of the articles")

    assert [len(exchange.calls) for exchange in conversation.exchanges] == [3, 3], (
        "each turn must carry its own three calls, not the running total"
    )
    assert all(
        [call["role"] for call in exchange.calls] == list(timing.ROLES)
        for exchange in conversation.exchanges
    )
    first = conversation.exchanges[0]
    assert 0 < first.calls_s < first.took_s, "the provider time for a turn cannot exceed the turn"


async def test_the_run_ends_with_a_per_role_baseline(spec, tmp_path, monkeypatch):
    """A run must leave behind the table this whole exercise is for."""
    monkeypatch.setattr("tests.live.transcript.RESULTS_DIR", tmp_path)
    recorder = Recorder()
    recorder.context = {"provider": "scripted", "model": "none"}

    node = "tests/live/test_x.py::test_a_call"
    with timing.collecting() as timeline:
        handle = Transcript(recorder.conversation(node), timeline)
        await _turn(spec, _client())
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
