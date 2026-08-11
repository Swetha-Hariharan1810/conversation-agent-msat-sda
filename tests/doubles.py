"""A chat model that answers like the provider without being one.

The timing tests need the *real* ``LLMClient`` — the clock lives inside it, so a
stub client that replaced it would be measuring itself — with something standing
exactly where ``langchain_openai``'s chat model stands. That is what this is.

    client = provider(Chat(delays={timing.GENERATE: 0.04}))
    await MsatSurveyAgent(client=client, spec=spec).run(state)

Each role can be given its own delay and its own failure, which is what makes it
usable for two different questions: whether a call's timing carries the label of
the call that produced it, and whether two calls that should overlap do.

The delays are the network. Nothing here sleeps for longer than a few hundredths
of a second, so the whole of both files runs on every ``pytest`` for nothing.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from msat_flow.llm import timing
from msat_flow.llm.client import LLMClient
from msat_flow.llm.schema import GuardAssessment, TurnDecision

# What each role costs unless a test says otherwise. They differ from each other
# on purpose: a timing that carried the wrong label would still look plausible if
# every call took the same time.
DELAYS = {timing.GUARD: 0.01, timing.EXTRACT: 0.02, timing.GENERATE: 0.04}


class Spoken:
    """What a chat model returns from ``ainvoke`` — content and nothing else."""

    def __init__(self, content: str) -> None:
        self.content = content


class Chain:
    """What ``with_structured_output`` returns: a chain that answers in a schema.

    Which of the two structured calls this is comes from the schema, because that
    is all the client passes down — the role label stays above, which is exactly
    the thing the timing tests are checking is applied correctly.
    """

    def __init__(self, chat: Chat, schema) -> None:
        self._chat = chat
        self._schema = schema

    async def ainvoke(self, messages):
        role = timing.GUARD if self._schema is GuardAssessment else timing.EXTRACT
        await self._chat.answer(role, messages)
        return self._chat.guard if role == timing.GUARD else self._chat.decision


class Chat:
    """A chat model with a per-role delay, a per-role failure, and a scripted answer."""

    def __init__(
        self,
        *,
        delays: dict[str, float] | None = None,
        guard: GuardAssessment | None = None,
        decision: TurnDecision | None = None,
        spoken: str = "And how helpful were they?",
        raises: Iterable[str] = (),
    ) -> None:
        self.delays = {**DELAYS, **(delays or {})}
        self.guard = guard if guard is not None else GuardAssessment()
        self.decision = decision if decision is not None else TurnDecision()
        self.spoken = spoken
        self.raises = frozenset(raises)
        # The roles this chat was asked for, in the order the requests were made.
        self.asked: list[str] = []
        # Every prompt it was sent, keyed by role, so a test can read what the
        # agent actually asked for rather than only what came back.
        self.prompts: dict[str, list[list[dict]]] = {}

    async def answer(self, role: str, messages=None) -> None:
        """Take this role's time, then fail if this role is scripted to."""
        self.asked.append(role)
        self.prompts.setdefault(role, []).append(messages or [])
        await asyncio.sleep(self.delays.get(role, 0.0))
        if role in self.raises:
            raise RuntimeError(f"{role} call failed")

    def sent(self, role: str) -> list[str]:
        """Every prompt sent for ``role``, flattened to one string per call."""
        return [
            "\n".join(str(message.get("content", "")) for message in messages)
            for messages in self.prompts.get(role, [])
        ]

    def with_structured_output(self, schema, method: str = "") -> Chain:
        return Chain(self, schema)

    async def ainvoke(self, messages) -> Spoken:
        await self.answer(timing.GENERATE, messages)
        return Spoken(self.spoken)


def provider(chat: Chat | None = None) -> LLMClient:
    """The real client, with the provider replaced and nothing else."""
    client = LLMClient()
    client._chat = chat if chat is not None else Chat()
    return client
