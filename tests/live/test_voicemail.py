"""Live end-to-end voicemail tests.

Verifies three things no guard-detection or unit test can show together:

1. The agent recognises a voicemail greeting in the full call context — the real
   intro line spoken, the real guard running, the real planner deciding what
   comes next.
2. It speaks the approved voicemail message VERBATIM — not a generated paraphrase,
   not a truncated version. The wording is what the business approved and what the
   platform will say to every recording it reaches, so it is exactly what must be
   tested.
3. The call ends there. No question slot is put to an answering machine; no consent
   gate is offered to a carrier announcement.

``test_full_calls.py`` covers both voicemail scenarios in its generic suite and
checks the disposition and slot accounting. This file adds the one assertion that
generic file cannot carry: that the spoken line is the exact approved text.

Run:
    MSAT_LIVE_TESTS=1 uv run pytest tests/live/test_voicemail.py -v

Or alongside the rest of the live suite:
    MSAT_LIVE_TESTS=1 uv run pytest tests/live -v
"""

from __future__ import annotations

import pytest

from msat_flow.agents.survey_agent import _last_message

from .loader import ids, scenarios
from .test_full_calls import _outcome, drive

# All call scenarios whose expected outcome is a voicemail message — currently
# the personal-greeting machine and the carrier-announcement machine. New voicemail
# scenarios added to calls.json are picked up automatically.
VOICEMAIL_CALLS = [
    c
    for c in scenarios("calls", key="calls")
    if (c.get("expect") or {}).get("disposition") == "voicemail_left"
]

# Every slot the survey can ask. A voicemail recording is never offered any of
# them, and having the list here makes a failure message precise rather than
# saying only that the assertion fired.
_SURVEY_SLOTS = frozenset(
    {
        "reviewed_resources",
        "no_review_reason",
        "resource_helpfulness",
        "improvement_feedback",
        "liked_most",
        "would_recommend",
        "staff_helpful",
        "overall_experience",
    }
)


@pytest.mark.live
@pytest.mark.parametrize("call", VOICEMAIL_CALLS, ids=ids(VOICEMAIL_CALLS))
async def test_voicemail_end_to_end(client, spec, transcript, call):
    """Voicemail greeting → verbatim message spoken, no survey, voicemail_left."""
    state, member = await drive(client, spec, call, transcript)
    outcome = _outcome(state)

    context = (
        f"\n  disposition : {outcome.get('disposition')}"
        f"\n  asked       : {member.asked}"
    )

    assert outcome.get("disposition") == "voicemail_left", (
        f"{call['id']}: expected voicemail_left, "
        f"got {outcome.get('disposition')!r}{context}"
    )

    asked_survey = _SURVEY_SLOTS & set(member.asked)
    assert not asked_survey, (
        f"{call['id']}: survey slot(s) {sorted(asked_survey)} were put to a "
        f"voicemail recording — a machine cannot consent to anything{context}"
    )

    spoken = _last_message(state.get("messages") or [], "assistant")
    vm_text = spec.of_kind("voicemail").text
    assert spoken.strip() == vm_text.strip(), (
        f"{call['id']}: voicemail message was not spoken verbatim.\n"
        f"  expected : {vm_text!r}\n"
        f"  got      : {spoken!r}{context}"
    )
