"""Per-slot attempt bookkeeping.

How many times one question may be put before the agent stops asking is a policy
number in ``data/slot_map.json``, not a constant here — the point at which
re-asking a satisfaction question turns from diligent into rude is a business
decision, and it should not require a code change to move.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SlotAttempt:
    name: str
    attempt_count: int = 0
    confirmed: bool = False
    last_value: str | None = None
    history: list[str] = field(default_factory=list)

    def record(self, value: str | None, *, success: bool) -> None:
        self.last_value = value
        if success:
            self.confirmed = True
            return
        self.attempt_count += 1
        if value:
            self.history.append(value)

    def is_exhausted(self, limit: int) -> bool:
        return self.attempt_count >= limit

    def to_dict(self) -> dict:
        return {
            "attempt_count": self.attempt_count,
            "confirmed": self.confirmed,
            "last_value": self.last_value,
        }

    @classmethod
    def from_dict(cls, name: str, data: dict | None) -> SlotAttempt:
        data = data or {}
        return cls(
            name=name,
            attempt_count=int(data.get("attempt_count", 0)),
            confirmed=bool(data.get("confirmed", False)),
            last_value=data.get("last_value"),
        )
