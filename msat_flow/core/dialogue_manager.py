"""Capture everything the member raised in a turn, not just the answer.

One extraction call can return a correction to an answer already recorded and
anything else raised in the same breath. Both land on the pending-intent ledger
here, and whatever is still open lands in the call outcome.

A satisfaction survey is the one call where the unprompted remark may be worth
more than the ratings, so nothing is dropped for being off-script.

What each remark IS, though, is the model's judgement and not this module's. The
extraction call already reads the turn; it now says of each thing raised whether
it is about member services, a request of us, a question about the question just
put, or an aside — and this module decides what the call then owes the member for
each. Wording is kept as the fallback for a remark the model left unlabelled,
which is the same arrangement guard detection runs (``core/guards.py``).
"""

from __future__ import annotations

from ..llm.schema import SecondaryIntentKind
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

# What the model's label means to the ledger. The two vocabularies are kept
# apart on purpose: one is what a model is asked about a sentence, the other is
# what this call then owes the member, and they are free to diverge.
_KINDS = {
    SecondaryIntentKind.MEMBER_SERVICES: IntentKind.UNSUPPORTED,
    SecondaryIntentKind.REQUEST: IntentKind.SIDE_REQUEST,
    SecondaryIntentKind.ABOUT_THE_SURVEY: IntentKind.CLARIFICATION,
    SecondaryIntentKind.ASIDE: IntentKind.OFF_TOPIC,
}

# Topics this agent cannot act on. It is a survey line, not member services, and
# pretending otherwise would leave someone waiting for a claim to be looked at.
#
# This is the FALLBACK, and only the fallback — used when the model returned a
# remark without saying what kind it was. Matching keywords against the model's
# own free-text paraphrase was never a classifier: "wants to know about her
# claim" is caught and "asked when someone will get back to her about the physio
# bill" is not, and which of those two the model writes is its choice, not the
# member's. Wording can still tell member services from everything else, which is
# the distinction with consequences, so that is all it is asked to do here.
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


def classify(intent) -> IntentKind:
    """What kind of thing the member raised: the model's answer, or its wording.

    ``intent`` is a ``SecondaryIntent`` from the extraction call. A bare string
    is accepted too — that is what a model returns when it has no kind to give,
    and it takes the fallback below rather than failing the turn.
    """
    kind = _KINDS.get(getattr(intent, "kind", None))
    if kind is not None:
        return kind
    return _classify_by_wording(intent_text(intent))


def _classify_by_wording(label: str) -> IntentKind:
    """The unlabelled case: member services if it sounds like it, else a request.

    Deliberately coarse. Reading a clarifying question or a piece of chit-chat
    out of a phrase is beyond what keywords can do honestly, and guessing at it
    would put the guess on the ledger — so an unlabelled remark is filed as
    something a person should look at, which is the safe way to be wrong.
    """
    text = (label or "").lower()
    if any(word in text for word in _MEMBER_SERVICES):
        return IntentKind.UNSUPPORTED
    return IntentKind.SIDE_REQUEST


def intent_text(intent) -> str:
    """The member's remark, from either shape the extraction call can return."""
    return str(getattr(intent, "text", intent) or "").strip()


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

        for raised in getattr(decision, "secondary_intents", None) or []:
            text = intent_text(raised)
            if not text:
                continue
            intents = add_intent(intents, PendingIntent(kind=classify(raised).value, raw_text=text))

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
