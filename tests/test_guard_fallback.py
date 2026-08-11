"""What the same live scenarios do when the provider is gone.

This is the one part of guard detection that must keep working on the day
everything else stops, so it is deliberately *not* under ``tests/live/``: it
needs no credentials, costs nothing, and runs on every ``pytest``.

It reads the live scenario table, so the two stay in step. Every turn written
down as something the model should catch is also a turn we can see the fallback's
answer to — including the ones the fallback misses, which are listed rather than
asserted away.
"""

from __future__ import annotations

import pytest

from msat_flow.agents.survey_agent import MsatSurveyAgent
from msat_flow.core.guards import SAFEGUARDING, match_patterns

from .live.loader import scenarios

GUARDS = scenarios("guards")


class DeadProvider:
    """Every call fails, the way a provider outage or an exhausted retry does.

    ``role`` is accepted and ignored, as the client contract has it: a stub that
    could not be told which of the turn's three calls it is standing in for would
    not be standing in for the real one.
    """

    async def structured(self, messages, schema, *, role: str = ""):
        raise RuntimeError("provider unavailable")

    async def text(self, messages, *, role: str = ""):
        raise RuntimeError("provider unavailable")


@pytest.mark.parametrize("row", GUARDS, ids=[row["id"] for row in GUARDS])
async def test_patterns_decide_when_the_provider_is_down(row):
    agent = MsatSurveyAgent(client=DeadProvider())
    outcome = await agent.check_guards({"ambiguous_counts": {}}, row["member"], row.get("last_agent", ""))
    assert outcome.kind == match_patterns(row["member"]), (
        f"\nscenario : {row['id']}"
        f"\nwith the provider down the patterns alone decide the outcome"
    )


async def test_the_provider_being_down_never_ends_the_call():
    """A failed guard degrades. Reading a turn is allowed to end a call; this is not."""
    agent = MsatSurveyAgent(client=DeadProvider())
    outcome = await agent.check_guards({"ambiguous_counts": {}}, "yes, a few of the articles", "")
    assert outcome.kind == "" and not outcome.handled


def test_the_safeguarding_floor_covers_what_the_fallback_must_never_miss():
    """The plain disclosures stay catchable with no model at all.

    These are the turns the pattern floor exists for: whatever the model says,
    and whether or not it can be reached, wording this plain fires the guard.
    """
    plain = [
        row for row in GUARDS if row["expect_call"] == SAFEGUARDING and match_patterns(row["member"])
    ]
    assert plain, "no scenario covers safeguarding wording the fallback can catch on its own"


def test_the_fallback_misses_are_written_down():
    """Report which live scenarios the patterns alone cannot decide.

    Not a pass/fail on the fallback — it is expected to miss the oblique ones,
    that is why the model call exists. This prints the list so the gap is a known
    quantity rather than a surprise during an outage.
    """
    misses = [
        row["id"]
        for row in GUARDS
        if row["expect_call"] and match_patterns(row["member"]) != row["expect_call"]
    ]
    false_alarms = [
        row["id"]
        for row in GUARDS
        if not row["expect_call"] and match_patterns(row["member"])
    ]
    print("\nfallback misses these guards entirely:")
    for scenario in misses or ["(none)"]:
        print(f"  - {scenario}")
    print("fallback fires on these turns that need no guard:")
    for scenario in false_alarms or ["(none)"]:
        print(f"  - {scenario}")
