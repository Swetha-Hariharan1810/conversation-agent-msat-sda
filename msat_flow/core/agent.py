"""BaseAgent — the shared infrastructure every survey agent inherits.

Composed exactly like the RCM blueprint: guards, slot management, signals and
dialogue management are mixins, and no domain logic lives here. To add an agent,
subclass, set ``AGENT_NAME`` and implement ``run``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..state import SurveyState
from .dialogue_manager import DialogueManagerMixin
from .guards import ConversationGuardsMixin
from .models import SlotAttempt
from .signals import SignalsMixin
from .slot_manager import SlotManagerMixin


class BaseAgent(ConversationGuardsMixin, SlotManagerMixin, SignalsMixin, DialogueManagerMixin, ABC):
    """Abstract base for survey agents."""

    AGENT_NAME: str = "base_agent"

    def __init__(self) -> None:
        self._slots: dict[str, SlotAttempt] = {}
        self._answers: dict[str, str] = {}
        self._pending_intents: list[dict] = []
        self._visited: list[str] = []

    @classmethod
    def from_state(cls, state: SurveyState) -> BaseAgent:
        """Rebuild the agent's working memory from persisted graph state."""
        agent = cls()
        agent._slots = {
            name: SlotAttempt.from_dict(name, data)
            for name, data in (state.get("slot_attempts") or {}).items()
        }
        agent._answers = dict(state.get("answers") or {})
        agent._pending_intents = list(state.get("pending_intents") or [])
        agent._visited = list(state.get("visited_nodes") or [])
        return agent

    def visit(self, node: str) -> None:
        """Record which script node this turn came from."""
        if node and (not self._visited or self._visited[-1] != node):
            self._visited.append(node)

    def persisted(self) -> dict:
        """The agent's working memory, as state updates."""
        return {
            "slot_attempts": self.slots_dict(),
            "answers": dict(self._answers),
            "pending_intents": list(self._pending_intents),
            "visited_nodes": list(self._visited),
        }

    async def execute(self, state: SurveyState) -> dict:
        return await self.run(state)

    @abstractmethod
    async def run(self, state: SurveyState) -> dict: ...
