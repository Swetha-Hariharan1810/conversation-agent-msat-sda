"""Guard detection against a real model.

Two layers, asked separately because they answer different questions:

* ``detect()`` — what the model alone makes of the turn. A failure here is a
  prompt problem, and ``prompts/detect_guards.system.md`` is where it is fixed.
* ``check_guards()`` — what the call actually does, patterns and precedence
  included. A failure here that the layer above passed is a composition problem,
  and ``core/guards.py`` is where that is fixed.

Scenarios live in ``scenarios/guards.json``. No survey content is named here.
"""

from __future__ import annotations

import pytest

from msat_flow.agents.survey_agent import MsatSurveyAgent
from msat_flow.core.guards import match_patterns, resolve
from msat_flow.llm.guard_detector import detect

from .loader import describe, ids, repeats, scenarios

GUARDS = scenarios("guards")


@pytest.mark.live
@pytest.mark.parametrize("row", GUARDS, ids=ids(GUARDS))
async def test_model_judges_the_turn(client, transcript, row):
    """The model's own verdict, with no patterns and no precedence involved."""
    expected = row["expect_model"]
    for attempt in range(1, repeats() + 1):
        assessment = await detect(
            client, last_agent_message=row.get("last_agent", ""), member_text=row["member"]
        )
        got = resolve(assessment)
        # Recorded before the assertion: a failed judgement is the exchange most
        # worth reading afterwards, and an assert that fires first loses it.
        transcript.exchange(
            scenario=row["id"],
            caller=row.get("last_agent", ""),
            member=row["member"],
            expected={"guard": expected or None},
            decided={
                "guard": got or None,
                "flags": sorted(name for name, on in assessment.model_dump().items() if on),
            },
        )
        assert got == expected, (
            f"\nscenario : {row['id']}"
            f"\nattempt  : {attempt}"
            f"\nmember   : {row['member']}"
            f"\nexpected : {expected or '(no guard)'}"
            f"\ngot      : {got or '(no guard)'}"
            f"\nflags    : {assessment.model_dump()}"
            f"\nwhy this scenario exists:\n{describe(row)}"
        )
        for field, value in (row.get("expect_flags") or {}).items():
            assert getattr(assessment, field) is value, (
                f"\nscenario : {row['id']}"
                f"\nflag     : {field} should be {value}"
                f"\nflags    : {assessment.model_dump()}"
                f"\nwhy this scenario exists:\n{describe(row)}"
            )


@pytest.mark.live
@pytest.mark.parametrize("row", GUARDS, ids=ids(GUARDS))
async def test_call_acts_on_the_turn(client, spec, transcript, row):
    """The whole guard: model, patterns and precedence together."""
    agent = MsatSurveyAgent(client=client, spec=spec)
    expected = row["expect_call"]
    for attempt in range(1, repeats() + 1):
        outcome = await agent.check_guards(
            {"ambiguous_counts": {}}, row["member"], row.get("last_agent", "")
        )
        transcript.exchange(
            scenario=row["id"],
            caller=row.get("last_agent", ""),
            member=row["member"],
            expected={"guard": expected or None},
            decided={
                "guard": outcome.kind or None,
                "patterns": match_patterns(row["member"]) or None,
                "ends_the_call": outcome.handled,
            },
        )
        assert outcome.kind == expected, (
            f"\nscenario : {row['id']}"
            f"\nattempt  : {attempt}"
            f"\nmember   : {row['member']}"
            f"\nexpected : {expected or '(no guard)'}"
            f"\ngot      : {outcome.kind or '(no guard)'}"
            f"\npatterns : {match_patterns(row['member']) or '(no match)'}"
            f"\nwhy this scenario exists:\n{describe(row)}"
        )
