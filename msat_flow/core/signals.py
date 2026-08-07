"""How an agent turn ends.

Three outcomes, each a plain state-update dict the graph node returns:
speak-and-wait, complete, escalate. Matches the RCM signal contract so the
orchestration boundary does not have to know anything survey-specific.

Note what "complete" means here: the call finished the way it was meant to,
which includes a member who declined to take part. A survey that ends because
somebody said "no thank you" is a correct outcome, not a failure, and reporting
it as one would bury the refusals in with the technical faults.
"""

from __future__ import annotations

from typing import Any

from ..state import SurveyState


class SignalsMixin:
    """Adds the three turn endings to the base agent."""

    AGENT_NAME: str = "base_agent"

    def speak(self, state: SurveyState, message: str, **updates: Any) -> dict:
        """Say something and wait for the member's reply."""
        return {
            "messages": [{"role": "assistant", "content": message}],
            "is_interrupt": True,
            "next_node": "call_workflow",
            "active_agent": self.AGENT_NAME,
            "last_agent_signal": {"agent": self.AGENT_NAME, "signal": "ask"},
            **updates,
        }

    def signal_complete(self, state: SurveyState, message: str, **updates: Any) -> dict:
        """Say the final line and end the call."""
        return {
            "messages": [{"role": "assistant", "content": message}],
            "is_interrupt": False,
            "next_node": "END",
            "phase": "done",
            "active_agent": self.AGENT_NAME,
            "last_agent_signal": {"agent": self.AGENT_NAME, "signal": "complete"},
            "metadata_events": [
                {"eventType": "AgentCallEvent", "data": {"eventName": "AgentCallEnded", "detail": "complete"}}
            ],
            **updates,
        }

    def signal_transfer(
        self,
        state: SurveyState,
        message: str,
        reason: str,
        *,
        initiator: str = "Agent",
        **updates: Any,
    ) -> dict:
        """Hand the call to a human and end this agent's run.

        The survey has exactly one of these: the document's own "I will get you
        to someone to reschedule".
        """
        return {
            "messages": [{"role": "assistant", "content": message}],
            "is_interrupt": False,
            "next_node": "END",
            "phase": "done",
            "active_agent": self.AGENT_NAME,
            "escalation_reason": reason,
            "last_agent_signal": {"agent": self.AGENT_NAME, "signal": "transfer", "reason": reason},
            "metadata_events": [
                {
                    "eventType": "AgentCallEvent",
                    "data": {
                        "eventName": "AgentCallTransfer",
                        "detail": reason,
                        "transferInitiator": initiator,
                    },
                }
            ],
            **updates,
        }
