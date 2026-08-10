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

from .loader import failure, ids, repeats, scenarios

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
                for key in (
                    "expect",
                    "expect_any",
                    "expect_absent",
                    "expect_corrections",
                    "expect_declines",
                    "expect_identity_detail",
                )
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
        recorded = {slot: _settled(slot, raw) for slot, raw in decision.values.items() if raw}
        seen = dict(
            event=decision.event_type,
            recorded=recorded or "nothing",
            corrections=decision.corrections or "none",
            declines=decision.declines_question,
            identity=decision.identity_detail.value or "none",
            attempt=attempt,
        )

        for slot, expected in (row.get("expect") or {}).items():
            assert recorded.get(slot, "") == expected, failure(
                row, expected=f"{slot}={expected!r}", got=recorded.get(slot) or "nothing", **seen
            )

        for slot in row.get("expect_any") or []:
            assert recorded.get(slot), failure(
                row, expected=f"{slot} recorded as anything", got="nothing", **seen
            )

        for slot in row.get("expect_absent") or []:
            assert not recorded.get(slot), failure(
                row, expected=f"{slot} not recorded", got=f"{slot}={recorded[slot]!r}", **seen
            )

        for slot, expected in (row.get("expect_corrections") or {}).items():
            assert _settled(slot, decision.corrections.get(slot, "")) == expected, failure(
                row, expected=f"correction {slot}={expected!r}", got=decision.corrections or "none", **seen
            )

        if "expect_declines" in row:
            assert decision.declines_question is row["expect_declines"], failure(
                row,
                expected=f"declines_question={row['expect_declines']}",
                got=decision.declines_question,
                **seen,
            )

        if "expect_identity_detail" in row:
            assert decision.identity_detail.value == row["expect_identity_detail"], failure(
                row,
                expected=f"identity_detail={row['expect_identity_detail']!r}",
                got=decision.identity_detail.value or "none",
                **seen,
            )
