"""Turn a planned action into something to say.

Most of the script is reference wording rather than a script to read: it is
passed to the model as the intent of the turn so the agent can acknowledge what
the member actually said — thank them for a long answer, read the options out
again after an unclear one, pick up where an interruption left off — while
asking for exactly what the document asks for.

Three kinds of line are exempt and are spoken exactly as written: the voicemail
message, the closing, and every off-script line. Those are approved wording, and
"approved" means the words, not the gist.

If no model is configured the script wording is used verbatim throughout. That
keeps the whole flow runnable, and testable, without a provider.

The wording sent to the model lives in ``prompts/speak_line.*.md``. What is left
here is composition: which of the optional sections this turn needs, and in what
order they are assembled.
"""

from __future__ import annotations

import re

from ..planner import Action, Plan
from . import prompts

# The document writes the policyholder's name as "[policyholder's full name]".
# Whatever else happens, that must never be said out loud.
_PLACEHOLDER = re.compile(r"\[[^\]]*\]")


def _bullets(items: tuple[str, ...] | list[str]) -> str:
    return "\n".join(f"  - {item}" for item in items)


def _sections(*parts: str) -> str:
    """Assemble the optional blocks of the user prompt, blank-line separated."""
    return "".join(f"\n{part}\n" for part in parts if part)


def fill_placeholders(text: str, values: dict[str, str]) -> str:
    """Substitute the document's bracketed placeholders, in order.

    The planner guarantees a value for every placeholder the greeting carries —
    the policyholder's name, or the declared stand-in when the work item has no
    name — so an unfilled bracket cannot reach the member.
    """
    supplied = list(values.values())
    return _PLACEHOLDER.sub(lambda _: supplied.pop(0) if supplied else "", text).replace("  ", " ")


def fallback(plan: Plan, ack: str = "") -> str:
    """What to say with no model: the script's wording, options appended.

    Used by the offline path and whenever the provider fails mid-call. One turn
    has no printed wording that is safe to speak — see the source note on 1b —
    so its goal stands in.
    """
    body = fill_placeholders(plan.text or plan.goal, plan.values)
    if plan.options:
        body = f"{body} " + "; ".join(plan.options) + "."
    return " ".join(part for part in (ack, plan.preamble, body) if part).strip()


def build_messages(
    plan: Plan,
    *,
    last_member_message: str = "",
    ack: str = "",
    retry_slot: str = "",
    retry_reason: str = "",
    attempt: int = 0,
    attempt_limit: int = 3,
) -> list[dict[str, str]]:
    """The messages this turn would send. Separated out so tests can read them."""
    values = {slot.replace("_", " "): value for slot, value in plan.values.items()}
    sections = _sections(
        prompts.render("speak_line.preamble", text=plan.preamble) if plan.preamble else "",
        prompts.render("speak_line.reference", text=plan.text) if plan.text else "",
        prompts.render("speak_line.options", options=_bullets(plan.options)) if plan.options else "",
        prompts.render(
            "speak_line.values",
            values=_bullets([f"{name}: {value}" for name, value in values.items()]),
        )
        if values
        else "",
        prompts.render("speak_line.context", member=last_member_message) if last_member_message else "",
        prompts.render(
            "speak_line.retry",
            slot=retry_slot.replace("_", " "),
            reason=retry_reason or "it was unclear",
            attempt=attempt,
            limit=attempt_limit,
        )
        if retry_slot
        else "",
        prompts.render("speak_line.acknowledge", ack=ack) if ack else "",
    )
    return [
        {"role": "system", "content": prompts.load("speak_line.system")},
        {
            "role": "user",
            "content": prompts.render("speak_line.user", goal=plan.goal or plan.text, sections=sections),
        },
    ]


async def generate(
    client,
    plan: Plan,
    *,
    last_member_message: str = "",
    ack: str = "",
    retry_slot: str = "",
    retry_reason: str = "",
    attempt: int = 0,
    attempt_limit: int = 3,
) -> str:
    """Produce the agent's line for ``plan``."""
    if plan.verbatim:
        # Approved wording, said exactly. A preamble still leads it in.
        return " ".join(part for part in (plan.preamble, plan.text) if part).strip()
    if client is None:
        return fallback(plan, ack)

    messages = build_messages(
        plan,
        last_member_message=last_member_message,
        ack=ack,
        retry_slot=retry_slot,
        retry_reason=retry_reason,
        attempt=attempt,
        attempt_limit=attempt_limit,
    )
    try:
        spoken = await client.text(messages)
    except Exception:  # pragma: no cover - provider failure must not drop the call
        return fallback(plan, ack)
    return spoken or fallback(plan, ack)


__all__ = ["Action", "build_messages", "fallback", "generate"]
