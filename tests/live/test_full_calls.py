"""Whole calls, greeting to closing line, against a real provider.

These run a call: the agent speaks, a scripted member answers whatever it was
actually asked, and the loop repeats until the call ends on its own. Roughly ten
agent turns, up to three model calls each, and the real planner deciding what
comes next.

This is the whole of the live suite bar guard detection, which is asked of the
model on its own because a safeguarding turn must be decided before anything
else in the call has a say. Everything else the model does — reading a turn,
recording an answer or refusing to, labelling what the member raised — is tested
here, through what came out at the end of a call rather than through what one
call returned in the middle of one. A turn read correctly that still produces
the wrong outcome is not a passing test, and the shape of this file is the
statement that the outcome is the thing.

Several things can only be seen here. That question 1a is asked and 1b is not.
That question 5 appears for a high-risk member and is reported as *skipped* — not
missing — for a rising one. That a safeguarding disclosure at question 2 stops
the survey and keeps what came before it. That a rating the member was merely
*nearest* to never reaches her file. That the disposition matches what happened
rather than what was intended.

The loop is deliberately the same one ``app_graph.py`` runs: rebuild the agent
from state each turn, run it, merge the update back. A driver that took a
shortcut here would be testing a call the platform never makes.
"""

from __future__ import annotations

import pytest

from msat_flow.agents.survey_agent import MsatSurveyAgent, _last_message
from msat_flow.state import initial_state

from .loader import describe, ids, scenarios

CALLS = scenarios("calls", key="calls")

# A reply nobody should ever have to give. Putting it in the script — rather than
# leaving the slot out — is what turns "the planner asked something it shouldn't"
# into a named failure instead of the call quietly running out of replies.
NEVER = "THIS MUST NEVER BE ASKED"

# A call is ten-ish turns. This is loose enough never to trip on a legitimate
# re-ask and tight enough that a loop cannot run up a provider bill.
MAX_TURNS = 40


class ScriptedMember:
    """Answers whatever the agent asks, from the scenario's reply table.

    Keyed by the slot the agent is waiting on, never by position, so the member
    answers the question actually put. A slot whose value is a list is consumed
    in order — that is how a member steps away and comes back to the same
    question.
    """

    def __init__(self, replies: dict) -> None:
        self._replies = {
            slot: list(value) if isinstance(value, list) else [value]
            for slot, value in replies.items()
        }
        self.asked: list[str] = []

    def reply_to(self, slot: str) -> str | None:
        self.asked.append(slot)
        queue = self._replies.get(slot)
        if not queue:
            return None
        return queue.pop(0) if len(queue) > 1 else queue[0]


def _merge(state: dict, update: dict) -> dict:
    """Fold one agent turn's update into the call state.

    ``messages`` appends rather than replaces — that is what the graph's
    ``add_messages`` reducer does, and getting it wrong would hand the agent an
    empty history every turn.
    """
    merged = {**state, **update}
    merged["messages"] = [*(state.get("messages") or []), *(update.get("messages") or [])]
    return merged


async def drive(client, spec, call: dict, transcript) -> tuple[dict, ScriptedMember]:
    """Run one whole call. Returns the final state and the member who took it."""
    member = ScriptedMember(call["replies"])
    # The platform's own constructor, not a hand-rolled dict. The work item lives
    # under `input_data`; a state that puts it anywhere else reads every payload
    # fact as empty, and a missing risk tier does not fail loudly — it silently
    # skips question 5 and reports a tidy result about a question nobody asked.
    state: dict = dict(initial_state(call["payload"]))

    for _ in range(MAX_TURNS):
        # Exactly what app_graph.call_workflow does.
        agent = MsatSurveyAgent.from_state(state)
        agent.client = client
        agent.spec = spec

        update = await agent.run(state)
        state = _merge(state, update)
        spoken = _last_message(update.get("messages") or [], "assistant")

        if not update.get("is_interrupt"):
            transcript.exchange(
                scenario=call["id"], caller=spoken, member="— call ended —", decided=_outcome(state)
            )
            return state, member

        awaiting = state.get("awaiting_slot") or ""
        said = member.reply_to(awaiting)
        if said is None:
            transcript.exchange(
                scenario=call["id"], caller=spoken, member=f"— no reply scripted for {awaiting!r} —"
            )
            pytest.fail(
                f"{call['id']}: the agent asked for {awaiting!r}, which the script has no reply for.\n"
                f"  it said   : {spoken}\n"
                f"  asked so far: {member.asked}\n"
                f"  add a reply for {awaiting!r}, or find out why it was asked."
            )
        transcript.exchange(scenario=call["id"], caller=spoken, member=said)
        state["messages"] = [*state["messages"], {"role": "user", "content": said}]

    pytest.fail(f"{call['id']}: call did not end within {MAX_TURNS} turns; asked {member.asked}")


def _outcome(state: dict) -> dict:
    return (state.get("output_data") or {}).get("call_outcome") or {}


@pytest.mark.live
@pytest.mark.parametrize("call", CALLS, ids=ids(CALLS))
async def test_the_whole_call(client, spec, transcript, call):
    state, member = await drive(client, spec, call, transcript)
    outcome = _outcome(state)
    expect = call["expect"]

    reported = outcome.get("open_intents") or []
    context = (
        f"\n  disposition : {outcome.get('disposition')}"
        f"\n  answers     : {outcome.get('answers')}"
        f"\n  declined    : {outcome.get('declined_questions')}"
        f"\n  skipped     : {[s.get('slot') for s in outcome.get('skipped_questions') or []]}"
        f"\n  missing     : {outcome.get('missing_questions')}"
        f"\n  reported    : {[(i.get('kind'), i.get('raw_text')) for i in reported]}"
        f"\n  asked       : {member.asked}"
        f"\n\n  why this call exists:\n{describe(call)}"
    )

    # Nothing the member was never meant to hear. Checked first: a call that
    # asked a rising-tier member about staff is wrong however it ends.
    for slot in expect.get("not_asked") or []:
        assert slot not in member.asked, (
            f"{call['id']}: asked for {slot!r}, which this member must never be asked{context}"
        )

    assert outcome.get("disposition") == expect["disposition"], (
        f"{call['id']}: expected disposition {expect['disposition']!r}, "
        f"got {outcome.get('disposition')!r}{context}"
    )

    for slot, value in (expect.get("answers") or {}).items():
        assert (outcome.get("answers") or {}).get(slot) == value, (
            f"{call['id']}: {slot} should be {value!r}, "
            f"got {(outcome.get('answers') or {}).get(slot)!r}{context}"
        )

    # Checked before the skipped/answers detail: "declined" is what the business
    # reads as "we asked and they would rather not say", and a member who was
    # working out what was being asked, or who could not hear us, must never be
    # reported that way. It is the difference between a survey gap and a slur on
    # somebody who was trying to answer.
    declined = set(outcome.get("declined_questions") or [])
    for slot in expect.get("not_declined") or []:
        assert slot not in declined, (
            f"{call['id']}: {slot!r} was reported as declined. The member answered it — "
            f"a question they had to ask us about first is not one they refused{context}"
        )

    skipped = {entry.get("slot") for entry in outcome.get("skipped_questions") or []}
    for slot in expect.get("skipped") or []:
        assert slot in skipped, (
            f"{call['id']}: {slot} should be reported as skipped, with the condition that ruled it "
            f"out — a question this member was never meant to get must not read as one we ran out "
            f"of time for{context}"
        )

    # What the call hands to a person to work through. The kind is the model's
    # judgement about something the member raised, so this is where that
    # judgement is checked against a real provider now — and it is checked
    # through the report rather than through the label, because the report is
    # what somebody acts on. A list that also holds the chit-chat is a list
    # nobody reads, which is how the one entry that mattered gets missed.
    kinds = [intent.get("kind") for intent in reported]
    for kind in expect.get("reported_intents") or []:
        assert kind in kinds, (
            f"{call['id']}: nothing was reported as {kind!r}. Something the member raised and "
            f"nobody on this call could deal with has to reach the outcome{context}"
        )

    for kind in expect.get("not_reported_intents") or []:
        assert kind not in kinds, (
            f"{call['id']}: {kind!r} was reported as something still needing a person. It was "
            f"dealt with on the call, or it asked for nothing at all{context}"
        )

    assert NEVER not in str(outcome.get("answers") or {}), (
        f"{call['id']}: a guard reply reached the answers{context}"
    )
