"""Record what was actually said on a live run, and write it to ``results/``.

A live run's real product is not the pass/fail — it is the exchange. What the
caller put, what the member said back, what the model made of it and what went
out next is the only evidence there is that these prompts work on words nobody
wrote a pattern for. A green run that keeps none of it tells you the assertions
held on a set of turns you can no longer read.

So every live test records its exchanges here, and the session writes two files:

* ``transcript.md`` — the conversations, in order, as something a person reads.
  This is the one to send to whoever owns the survey wording.
* ``run.json`` — the same thing structured, so two runs can be diffed and a
  model change can be seen rather than guessed at.

Nothing here asserts. A test that fails still writes its exchange, and that is
the point: the transcript of a failure is the most useful thing in the directory.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = Path(os.getenv("MSAT_RESULTS_DIR") or REPO_ROOT / "results")

CALLER = "Caller"
MEMBER = "Member"


@dataclass
class Exchange:
    """One caller turn, one member turn, and what the agent did with it."""

    scenario: str
    caller: str
    member: str
    decided: dict = field(default_factory=dict)
    expected: dict = field(default_factory=dict)
    reply: str = ""
    elapsed_s: float = 0.0


@dataclass
class Conversation:
    """Every exchange one test produced, and how it ended."""

    test: str
    exchanges: list[Exchange] = field(default_factory=list)
    outcome: str = "not run"

    @property
    def failed(self) -> bool:
        return self.outcome == "failed"


class Recorder:
    """Collects conversations across the session, keyed by pytest node id."""

    def __init__(self) -> None:
        self.conversations: dict[str, Conversation] = {}
        self.started = datetime.now(timezone.utc)
        self.context: dict[str, str] = {}

    def conversation(self, test: str) -> Conversation:
        return self.conversations.setdefault(test, Conversation(test=test))

    def outcome(self, test: str, outcome: str) -> None:
        if test in self.conversations:
            self.conversations[test].outcome = outcome

    # ── writing ──────────────────────────────────────────────────────────

    def write(self) -> Path | None:
        """Write both files. Returns the directory, or None if nothing ran."""
        if not self.conversations:
            return None
        stamp = self.started.strftime("%Y-%m-%dT%H-%M-%SZ")
        directory = RESULTS_DIR / "live" / stamp
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "run.json").write_text(self._json(), encoding="utf-8")
        (directory / "transcript.md").write_text(self._markdown(), encoding="utf-8")
        latest = RESULTS_DIR / "live" / "latest.md"
        latest.write_text(self._markdown(), encoding="utf-8")
        return directory

    def _tally(self) -> dict[str, int]:
        tally: dict[str, int] = {}
        for conversation in self.conversations.values():
            tally[conversation.outcome] = tally.get(conversation.outcome, 0) + 1
        return tally

    def _json(self) -> str:
        return json.dumps(
            {
                "started": self.started.isoformat(),
                "context": self.context,
                "tally": self._tally(),
                "conversations": [
                    {
                        "test": conversation.test,
                        "outcome": conversation.outcome,
                        "exchanges": [asdict(exchange) for exchange in conversation.exchanges],
                    }
                    for conversation in self.conversations.values()
                ],
            },
            indent=2,
            ensure_ascii=False,
        )

    def _markdown(self) -> str:
        tally = self._tally()
        summary = ", ".join(f"{count} {name}" for name, count in sorted(tally.items()))
        lines = [
            f"# Live run — {self.started.strftime('%Y-%m-%d %H:%M UTC')}",
            "",
            " · ".join(f"**{key}** {value}" for key, value in self.context.items()) or "_no context_",
            "",
            f"{len(self.conversations)} conversations — {summary}",
            "",
            "Every exchange the live tests put to the model, in the order they ran.",
            "Failures are kept, and marked; they are the ones worth reading.",
            "",
        ]

        failed = [c for c in self.conversations.values() if c.failed]
        if failed:
            lines += ["## Failures", ""]
            lines += [f"- `{conversation.test}`" for conversation in failed]
            lines += [""]

        lines += ["---", ""]
        for conversation in self.conversations.values():
            mark = {"passed": "✓", "failed": "✗", "skipped": "–"}.get(conversation.outcome, "?")
            lines += [f"## {mark} {conversation.test}", ""]
            for exchange in conversation.exchanges:
                lines += self._exchange_lines(exchange)
            lines += ["---", ""]
        return "\n".join(lines)

    @staticmethod
    def _exchange_lines(exchange: Exchange) -> list[str]:
        lines = [f"**{exchange.scenario}**", ""]
        if exchange.caller:
            lines += [f"> **{CALLER}** — {exchange.caller}", ">"]
        lines += [f"> **{MEMBER}** — {exchange.member}", ""]
        if exchange.reply:
            lines += [f"> **{CALLER}** — {exchange.reply}", ""]
        if exchange.expected:
            lines += [f"- expected: `{_compact(exchange.expected)}`"]
        if exchange.decided:
            lines += [f"- decided: `{_compact(exchange.decided)}`"]
        if exchange.elapsed_s:
            lines += [f"- took: {exchange.elapsed_s:.1f}s"]
        lines += [""]
        return lines


def _compact(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


class TestTranscript:
    """The handle a single test writes through."""

    __slots__ = ("_conversation", "_t0")

    def __init__(self, conversation: Conversation) -> None:
        self._conversation = conversation
        self._t0 = time.monotonic()

    def exchange(
        self,
        *,
        scenario: str,
        member: str,
        caller: str = "",
        decided: dict | None = None,
        expected: dict | None = None,
        reply: str = "",
    ) -> None:
        """Record one exchange. Timing is measured from the start of the test.

        With the default ``MSAT_LIVE_REPEAT=1`` that is the round trip. Raise the
        repeat count and it becomes cumulative, which is what you want when the
        question is whether the whole scenario stays inside a human pause.
        """
        self._conversation.exchanges.append(
            Exchange(
                scenario=scenario,
                caller=caller,
                member=member,
                decided=decided or {},
                expected=expected or {},
                reply=reply,
                elapsed_s=round(time.monotonic() - self._t0, 3),
            )
        )
