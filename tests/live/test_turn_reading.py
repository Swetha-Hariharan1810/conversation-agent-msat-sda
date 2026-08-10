"""Reading a member turn against a real model.

The extraction contract is the thing under test, and it is a contract about
restraint as much as about recall: a choice the member did not give must not be
recorded, and "no feedback" must not be read as a refusal. Roughly half of
``scenarios/turns.json`` asserts that nothing was recorded.

Values are checked after normalisation and validation — the same pipeline a live
call puts them through — because a raw string the validator would reject is not
an answer, and asserting on the raw model output would call it one.
"""

from __future__ import annotations

import pytest

from msat_flow.llm.extractor import extract
from msat_flow.slots.pipeline import accept

from .loader import describe, ids, repeats, scenarios

TURNS = scenarios("turns")


def _settled(slot: str, raw: str) -> str:
    """What the pipeline makes of a raw answer, or "" if it rejects it."""
    if not raw:
        return ""
    result = accept(slot, raw)
    return result.value if result.accepted else ""


@pytest.mark.live
@pytest.mark.parametrize("row", TURNS, ids=ids(TURNS))
async def test_the_turn_is_read_as_written(client, spec, transcript, row):
    awaiting = row.get("awaiting", "")
    for attempt in range(1, repeats() + 1):
        decision = await extract(
            client,
            spec,
            asked_slots=tuple(filter(None, [awaiting])),
            last_agent_message=row.get("last_agent", ""),
            member_text=row["member"],
        )
        # Before the assertions, so a turn that was read wrongly is legible in
        # the transcript rather than only in a traceback.
        transcript.exchange(
            scenario=row["id"],
            caller=row.get("last_agent", ""),
            member=row["member"],
            expected={
                key: row[key]
                for key in ("expect", "expect_absent", "expect_corrections", "expect_declines")
                if key in row
            },
            decided={
                "event": str(decision.event_type),
                "recorded": {
                    slot: _settled(slot, raw) for slot, raw in decision.values.items() if raw
                },
                "raw_values": decision.values,
                "corrections": decision.corrections,
                "declines": decision.declines_question,
                "identity_detail": decision.identity_detail.value,
                "secondary_intents": decision.secondary_intents,
            },
        )
        context = (
            f"\nscenario : {row['id']}"
            f"\nattempt  : {attempt}"
            f"\nmember   : {row['member']}"
            f"\nevent    : {decision.event_type}"
            f"\nvalues   : {decision.values}"
            f"\ncorrect. : {decision.corrections}"
            f"\ndeclines : {decision.declines_question}"
            f"\nidentity : {decision.identity_detail!r}"
            f"\nwhy this scenario exists:\n{describe(row)}"
        )

        for slot, expected in (row.get("expect") or {}).items():
            assert _settled(slot, decision.values.get(slot, "")) == expected, (
                f"\n{slot} should have been recorded as {expected!r}{context}"
            )

        for slot in row.get("expect_absent") or []:
            recorded = _settled(slot, decision.values.get(slot, ""))
            assert not recorded, f"\n{slot} was recorded as {recorded!r} and should not have been{context}"

        for slot, expected in (row.get("expect_corrections") or {}).items():
            assert _settled(slot, decision.corrections.get(slot, "")) == expected, (
                f"\n{slot} should have arrived as a correction of {expected!r}{context}"
            )

        if "expect_declines" in row:
            assert decision.declines_question is row["expect_declines"], (
                f"\ndeclines_question should be {row['expect_declines']}{context}"
            )

        if "expect_identity_detail" in row:
            assert decision.identity_detail.value == row["expect_identity_detail"], (
                f"\nidentity_detail should be {row['expect_identity_detail']!r}{context}"
            )
