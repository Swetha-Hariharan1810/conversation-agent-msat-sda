"""Read one member turn into a TurnDecision.

The whole questionnaire is offered to the model every turn — it is eight
questions, and a member who answers the next one early or comes back to an
earlier one is being helpful, not confusing. What is *not* offered is any
freedom over choice answers: each choice slot is listed with the exact option
values it accepts, because a rating the member did not give is worse than no
rating at all.

The wording sent to the model lives in ``prompts/extract_turn.*.md``. What is
left here is which slots are put in front of it, and what is thrown away when it
answers.
"""

from __future__ import annotations

from ..script.spec import SlotType, SurveySpec
from ..slots.types import describe, slot_spec
from . import prompts, timing
from .schema import TurnDecision


def _catalogue(spec: SurveySpec, slots: list[str]) -> str:
    lines = []
    for slot in slots:
        declared = slot_spec(slot)
        line = f"- {slot} ({declared.type.value}): {describe(slot)}"
        if declared.type is SlotType.CHOICE:
            allowed = ", ".join(f'"{option.value}" ({option.label})' for option in declared.options)
            line += f"\n    one of: {allowed}"
        lines.append(line)
    return "\n".join(lines)


def relevant_slots(spec: SurveySpec, asked_slots: tuple[str, ...]) -> list[str]:
    """Slots the member could plausibly be answering right now.

    The question that was just put comes first, then the rest of the survey in
    the document's order. Payload-only slots are never offered: the risk tier
    decides which questions this member gets, and nothing said on the call may
    change it.
    """
    candidates = [*asked_slots, *spec.question_slots]
    gates = [turn.slot for turn in spec.agent_turns if turn.kind in ("intro", "consent", "reschedule_offer")]
    seen: list[str] = []
    for slot in [*candidates, *gates]:
        if slot and slot not in seen and slot not in spec.payload_only_slots:
            seen.append(slot)
    return seen


def build_messages(
    spec: SurveySpec, *, asked_slots: tuple[str, ...], last_agent_message: str, member_text: str
) -> list[dict[str, str]]:
    """The messages this turn would send. Separated out so tests can read them."""
    return [
        {"role": "system", "content": prompts.load("extract_turn.system")},
        {
            "role": "user",
            "content": prompts.render(
                "extract_turn.user",
                slots=_catalogue(spec, relevant_slots(spec, asked_slots)),
                last_agent=last_agent_message or "(nothing yet)",
                member=member_text,
            ),
        },
    ]


async def extract(
    client,
    spec: SurveySpec,
    *,
    asked_slots: tuple[str, ...],
    last_agent_message: str,
    member_text: str,
) -> TurnDecision:
    messages = build_messages(
        spec,
        asked_slots=asked_slots,
        last_agent_message=last_agent_message,
        member_text=member_text,
    )
    decision = await client.structured(messages, TurnDecision, role=timing.EXTRACT)

    # Drop unknown slot NAMES only. The values themselves still have to survive
    # normalisation and validation, which is where an invented option is caught.
    allowed = set(spec.slots) - set(spec.payload_only_slots)
    decision.values = {key: value for key, value in decision.values.items() if key in allowed}
    decision.corrections = {key: value for key, value in decision.corrections.items() if key in allowed}
    return decision
