"""How long each of the three model calls took, when somebody is asking.

A turn can make three provider calls — the guard call, the extraction call and
the line the agent speaks — and until now the only number anyone had was how long
the whole turn took. That is enough to see that a turn was slow and not enough to
do anything about it: a two-second turn is three calls, and which of the three it
was decides whether the answer is a smaller model, a shorter prompt, or dropping
a call entirely.

So each call is labelled with the role it plays and timed on its own.

## Nothing is measured unless something is collecting

``measure()`` looks for an active :class:`Timeline` and, finding none, does
nothing at all — no clock read, no allocation, no branch beyond the lookup. On a
real call nothing collects, so this module costs one ``ContextVar.get`` per
provider call and changes no behaviour whatsoever. The live tests collect; that
is what puts per-call timings in the transcripts.

    from msat_flow.llm import timing

    with timing.collecting() as timeline:
        await agent.run(state)
    for call in timeline.calls:
        print(call.role, call.seconds)

## Failed calls are timed too

A call that raises is recorded with ``ok=False`` and the time it burned before
failing. A provider timeout is the slowest thing that can happen on a turn, and
dropping those samples would produce a latency table that looks best exactly when
the call went worst.
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

# The three roles a provider call plays in a turn. Labels, not a registry:
# ``measure`` accepts anything, and these exist so the call sites and the reports
# spell them the same way.
GUARD = "guard"
EXTRACT = "extract"
GENERATE = "generate"
ROLES: tuple[str, ...] = (GUARD, EXTRACT, GENERATE)

# What a call with no role given is filed under, so an unlabelled call site shows
# up in the table as a gap to close rather than vanishing from the totals.
UNLABELLED = "unlabelled"


@dataclass(frozen=True)
class Call:
    """One provider call: what it was for, how long it took, whether it worked."""

    role: str
    seconds: float
    ok: bool = True

    def as_dict(self) -> dict:
        return {"role": self.role, "seconds": round(self.seconds, 3), "ok": self.ok}


class Timeline:
    """The calls recorded while this timeline was active.

    ``drain()`` returns everything since the last drain, which is how a
    transcript attributes calls to the turn that made them without the agent
    having to know anything about timing.
    """

    __slots__ = ("calls", "_drained")

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self._drained = 0

    def add(self, call: Call) -> None:
        self.calls.append(call)

    def drain(self) -> list[Call]:
        """Calls recorded since the previous drain."""
        fresh = self.calls[self._drained :]
        self._drained = len(self.calls)
        return fresh

    def __len__(self) -> int:
        return len(self.calls)


_active: ContextVar[Timeline | None] = ContextVar("msat_llm_timeline", default=None)


@contextmanager
def collecting(timeline: Timeline | None = None) -> Iterator[Timeline]:
    """Record provider calls made in this context.

    Nested collection replaces rather than fans out: one collector at a time is
    all anything here needs, and stacking them would double-count.
    """
    timeline = timeline if timeline is not None else Timeline()
    token = _active.set(timeline)
    try:
        yield timeline
    finally:
        _active.reset(token)


def active() -> Timeline | None:
    return _active.get()


@contextmanager
def measure(role: str) -> Iterator[None]:
    """Time the block and file it under ``role`` — if anything is collecting.

    With no collector this is a lookup and a yield, which is what makes it safe
    to leave in the client's hot path.
    """
    timeline = _active.get()
    if timeline is None:
        yield
        return
    started = time.perf_counter()
    ok = True
    try:
        yield
    except BaseException:
        ok = False
        raise
    finally:
        timeline.add(Call(role or UNLABELLED, time.perf_counter() - started, ok))


# ── reading the numbers back ─────────────────────────────────────────────


def percentile(values: Sequence[float], share: float) -> float:
    """Nearest-rank percentile.

    Nearest-rank rather than interpolated on purpose: every number it reports is
    a duration that actually happened, and at the sample sizes a live run
    produces — tens of calls, not thousands — an interpolated p95 invents a
    figure between two real ones and reads as more precise than the evidence is.
    """
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = min(len(ordered), max(1, math.ceil(share * len(ordered))))
    return ordered[rank - 1]


@dataclass(frozen=True)
class RoleStats:
    """What one role's calls added up to over a run."""

    role: str
    count: int
    total_s: float
    p50_s: float
    p95_s: float
    slowest_s: float
    failures: int = 0

    def as_dict(self) -> dict:
        return {
            "role": self.role,
            "count": self.count,
            "total_s": round(self.total_s, 3),
            "p50_s": round(self.p50_s, 3),
            "p95_s": round(self.p95_s, 3),
            "slowest_s": round(self.slowest_s, 3),
            "failures": self.failures,
        }


def summarise(calls: Sequence[Call]) -> dict[str, RoleStats]:
    """Per-role statistics, in ``ROLES`` order with any stragglers after.

    Roles that made no calls are left out entirely rather than reported as zero:
    a run that never reached the extractor should say so by its absence, not by a
    row of zeroes that reads like a fast call.
    """
    grouped: dict[str, list[Call]] = {}
    for call in calls:
        grouped.setdefault(call.role, []).append(call)

    ordered = [role for role in ROLES if role in grouped]
    ordered += [role for role in grouped if role not in ROLES]

    stats: dict[str, RoleStats] = {}
    for role in ordered:
        seconds = [call.seconds for call in grouped[role]]
        stats[role] = RoleStats(
            role=role,
            count=len(seconds),
            total_s=sum(seconds),
            p50_s=percentile(seconds, 0.50),
            p95_s=percentile(seconds, 0.95),
            slowest_s=max(seconds),
            failures=sum(1 for call in grouped[role] if not call.ok),
        )
    return stats


__all__ = [
    "EXTRACT",
    "GENERATE",
    "GUARD",
    "ROLES",
    "UNLABELLED",
    "Call",
    "RoleStats",
    "Timeline",
    "active",
    "collecting",
    "measure",
    "percentile",
    "summarise",
]
