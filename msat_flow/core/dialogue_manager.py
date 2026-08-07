"""Capture everything the member raised in a turn, not just the answer.

One extraction call can return a correction to an answer already recorded and
anything else raised in the same breath. Both land on the pending-intent ledger
here, and whatever is still open lands in the call outcome.

A satisfaction survey is the one call where the unprompted remark may be worth
more than the ratings, so nothing is dropped for being off-script.
"""

from __future__ import annotations

from ..script.spec import SurveySpec
from .pending_intents import (
    ACK_ONLY_KINDS,
    IntentKind,
    IntentStatus,
    PendingIntent,
    add_intent,
    mark,
    open_intents,
)

# Topics this agent cannot act on. It is a survey line, not member services, and
# pretending otherwise would leave someone waiting for a claim to be looked at.
_MEMBER_SERVICES = (
    "claim",
    "policy",
    "premium",
    "benefit",
    "coverage",
    "billing",
    "invoice",
    "payment",
    "deductible",
    "id card",
)


def classify(*, correction_target: str | None, label: str | None) -> IntentKind:
    if correction_target:
        return IntentKind.CORRECTION
    text = (label or "").lower()
    if any(word in text for word in _MEMBER_SERVICES):
        return IntentKind.UNSUPPORTED
    if not text:
        return IntentKind.OFF_TOPIC
    return IntentKind.SIDE_REQUEST


class DialogueManagerMixin:
    """Adds multi-request capture and acknowledgement to the base agent."""

    _pending_intents: list[dict]
    spec: SurveySpec

    def capture_and_triage(self, decision) -> None:
        """Record corrections and secondary requests from one extraction result."""
        if decision is None:
            return
        intents = list(self._pending_intents)

        for target in getattr(decision, "corrections", None) or {}:
            intents = add_intent(
                intents,
                PendingIntent(kind=IntentKind.CORRECTION.value, raw_text=f"correct {target}", target=target),
            )

        for label in getattr(decision, "secondary_intents", None) or []:
            label = (label or "").strip()
            if not label:
                continue
            intents = add_intent(
                intents,
                PendingIntent(kind=classify(correction_target=None, label=label).value, raw_text=label),
            )

        self._pending_intents = intents

    def side_request_ack(self) -> str:
        """One short line acknowledging what we cannot act on, said exactly once."""
        fresh = open_intents(self._pending_intents, kinds=ACK_ONLY_KINDS)
        if not fresh:
            return ""
        self._pending_intents = mark(
            self._pending_intents, kinds=ACK_ONLY_KINDS, status=IntentStatus.ACKNOWLEDGED
        )
        return self.spec.policy.line("side_request_ack")

    def resolve_intents(self, *, target: str) -> None:
        """Mark corrections for ``target`` resolved once the new answer is recorded."""
        self._pending_intents = [
            {**intent, "status": IntentStatus.RESOLVED.value}
            if intent.get("kind") == IntentKind.CORRECTION.value and intent.get("target") == target
            else intent
            for intent in self._pending_intents
        ]
