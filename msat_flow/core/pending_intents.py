"""Anything the member raised that we have not dealt with yet.

Mirrors the RCM pending-intent ledger: a request is captured the moment it is
heard and stays OPEN until it is answered, acknowledged, or explicitly dropped.
Nothing the member says is silently discarded — on a satisfaction call the thing
they raised unprompted is often the most useful sentence of the whole survey.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum


class IntentKind(StrEnum):
    CORRECTION = "correction"  # member revised an answer they already gave
    SIDE_REQUEST = "side_request"  # member asked us for something
    UNSUPPORTED = "unsupported"  # about their policy or the program, not this call's job
    CLARIFICATION = "clarification"  # a question about the question we just put
    OFF_TOPIC = "off_topic"  # a remark that asks nothing of us


class IntentStatus(StrEnum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    # Heard, kept, and owed nothing. An aside is not a request, and filing it as
    # one is how a report of things a person must action fills up with remarks
    # about the weather. It is still written down — on this call the unprompted
    # remark may be the most useful sentence of the survey — it is just not
    # written down as work.
    NOTED = "noted"


# Kinds that must be spoken aloud once but must not rewind the survey.
#
# ``UNSUPPORTED`` and nothing else, because there is exactly one acknowledgement
# to say — "I'll note that and pass it on to the program team" — and it is a
# sentence about member services. Said back to somebody telling us their daughter
# is visiting, it is worse than saying nothing: it answers a remark that asked
# nothing with a promise nobody wanted. ``OFF_TOPIC`` and ``CLARIFICATION`` are
# answered by the line the generator composes with the member's own words in
# hand, not by this one.
ACK_ONLY_KINDS = frozenset({IntentKind.UNSUPPORTED.value})


@dataclass
class PendingIntent:
    kind: str
    raw_text: str
    target: str | None = None
    status: str = field(default=IntentStatus.OPEN.value)

    def to_dict(self) -> dict:
        return asdict(self)


def add_intent(intents: list[dict], intent: PendingIntent) -> list[dict]:
    """Append unless an identical open intent is already queued."""
    incoming = intent.to_dict()
    for existing in intents:
        same = (
            existing.get("kind") == incoming["kind"]
            and existing.get("target") == incoming["target"]
            and existing.get("status") == IntentStatus.OPEN.value
        )
        if same:
            return intents
    return [*intents, incoming]


def open_intents(intents: list[dict], *, kinds: frozenset[str] | None = None) -> list[dict]:
    return [
        intent
        for intent in intents or []
        if intent.get("status") == IntentStatus.OPEN.value and (kinds is None or intent.get("kind") in kinds)
    ]


def mark(intents: list[dict], *, kinds: frozenset[str], status: IntentStatus) -> list[dict]:
    return [
        {**intent, "status": status.value}
        if intent.get("kind") in kinds and intent.get("status") == IntentStatus.OPEN.value
        else intent
        for intent in intents or []
    ]
