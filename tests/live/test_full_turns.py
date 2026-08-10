"""Whole turns through the agent, against a real provider.

The layers above test one model call each. This tests that they compose: a turn
goes in, the guard call runs first, the extractor runs only if the guard let it
through, and something the member could actually hear comes back out.

Three turns, chosen because each proves a different thing about the ordering:
an ordinary answer that must reach the file, a safeguarding turn that must NOT,
and a hold that must not lose the question it interrupted.
"""

from __future__ import annotations

import pytest

from msat_flow.agents.survey_agent import MsatSurveyAgent

from .loader import scenarios

GUARDS = {row["id"]: row for row in scenarios("guards")}
TURNS = {row["id"]: row for row in scenarios("turns")}

PAYLOAD = {
    "workflow_subtype": "MEMBER_SATISFACTION_SURVEY",
    "call_context": {"call_id": "rcm-live-test", "language": "en-US"},
    "policyholder": {"first_name": "Margaret", "last_name": "Ellison", "risk_tier": "high"},
}


def _state(spec, member: str, *, awaiting: str) -> dict:
    """Mid-survey state: identity and consent settled, one question outstanding."""
    return {
        "messages": [
            {"role": "assistant", "content": "…"},
            {"role": "user", "content": member},
        ],
        "payload": PAYLOAD,
        "identity": "confirmed",
        "consent": "granted",
        "survey_started": True,
        "awaiting_slot": awaiting,
        "ambiguous_counts": {},
        "workflow_subtype": PAYLOAD["workflow_subtype"],
    }


def _spoken(result: dict) -> str:
    for message in reversed(result.get("messages") or []):
        content = message.get("content") if isinstance(message, dict) else getattr(message, "content", "")
        role = message.get("role") if isinstance(message, dict) else getattr(message, "type", "")
        if content and role in ("assistant", "ai"):
            return str(content)
    return ""


@pytest.mark.live
async def test_an_ordinary_answer_is_recorded_and_the_survey_moves_on(client, spec):
    row = TURNS["plain_yes"]
    slot = row["awaiting"]
    agent = MsatSurveyAgent(client=client, spec=spec)
    result = await agent.run(_state(spec, row["member"], awaiting=slot))

    assert agent.answer(slot) == row["expect"][slot], (
        f"{slot} should have been recorded as {row['expect'][slot]!r}, got {agent.answer(slot)!r}"
    )
    assert _spoken(result).strip(), "the agent said nothing back"
    assert result.get("phase") == "survey"
    assert result.get("awaiting_slot") != slot, (
        "the survey did not move past the question it just got an answer to"
    )


@pytest.mark.live
async def test_a_safeguarding_turn_stops_the_survey_and_is_never_filed(client, spec):
    """The ordering that matters most, end to end.

    The member's words here also contain a usable answer. They must not be
    recorded: a turn that trips the safety guard is never read as survey content,
    and the line that goes out is the approved one, word for word.
    """
    row = GUARDS["safeguarding.hopelessness_oblique"]
    slot = spec.question_slots[0]
    agent = MsatSurveyAgent(client=client, spec=spec)
    result = await agent.run(_state(spec, row["member"], awaiting=slot))

    assert not agent.answer(slot), "a safeguarding turn was filed as a survey answer"
    assert result.get("disposition") == "safeguarding_handoff", result.get("disposition")
    assert spec.policy.line("safeguarding_handoff") in _spoken(result), (
        "the handoff was paraphrased; this line is approved wording and is spoken exactly"
    )


@pytest.mark.live
async def test_a_hold_keeps_the_question_it_interrupted(client, spec):
    """A pause must not cost the member the question they were part way through."""
    row = GUARDS["hold.door"]
    slot = spec.question_slots[0]
    agent = MsatSurveyAgent(client=client, spec=spec)
    result = await agent.run(_state(spec, row["member"], awaiting=slot))

    assert result.get("awaiting_slot", slot) == slot, "the pending question was dropped over a pause"
    assert _spoken(result).strip(), "the agent said nothing while the member stepped away"
    assert not agent.answer(slot), "a pause was recorded as an answer"
