"""Ask the model whether a member turn is one the survey cannot carry on through.

This is the first thing asked about any turn, ahead of reading it as an answer,
because two of the five outcomes must never wait on the survey and must never be
filed against a question.

The call is deliberately narrow. It is not given the questionnaire, the slots or
the answers so far — only what the caller just said and what the member said back
— because widening it would let a survey answer argue its way into a safeguarding
decision. It returns five booleans and nothing else; the precedence between them
stays in ``core/guards.py``.

The wording sent to the model lives in ``prompts/detect_guards.*.md``.
"""

from __future__ import annotations

from . import prompts
from .schema import GuardAssessment


def build_messages(*, last_agent_message: str = "", member_text: str) -> list[dict[str, str]]:
    """The messages this turn would send. Separated out so tests can read them."""
    return [
        {"role": "system", "content": prompts.load("detect_guards.system")},
        {
            "role": "user",
            "content": prompts.render(
                "detect_guards.user",
                last_agent=last_agent_message or "(nothing yet)",
                member=member_text,
            ),
        },
    ]


async def detect(client, *, last_agent_message: str = "", member_text: str) -> GuardAssessment:
    """What the model makes of this turn.

    Raises whatever the provider raises. The caller decides what a failure means;
    here it would be wrong to swallow one, because a swallowed failure looks
    exactly like a turn with nothing in it.
    """
    return await client.structured(
        build_messages(last_agent_message=last_agent_message, member_text=member_text),
        GuardAssessment,
    )


__all__ = ["GuardAssessment", "build_messages", "detect"]
