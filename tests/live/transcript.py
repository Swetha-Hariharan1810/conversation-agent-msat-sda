"""Record what was actually said on a live run, and write it to ``results/``.

A live run's real product is not the pass/fail — it is the exchange. What the
caller put, what the member said back, what the model made of it and what went
out next is the only evidence there is that these prompts work on words nobody
wrote a pattern for. A green run that keeps none of it tells you the assertions
held on a set of turns you can no longer read.

## Written as it goes, one file per test

Each test's files are written the moment that test finishes, not at the end of
the session. A live run is slow — nine whole calls is several minutes of provider
latency — and a run that is interrupted, times out, or is killed halfway must
still leave behind everything it had got through. Nothing is buffered to the end,
because the end is exactly what a long run does not always reach.

    results/live/<utc stamp>/
        index.md                     a row per test, appended as each finishes
        run.jsonl                    one JSON object per test, appended
        test_full_calls/
            003__the_whole_call__complete_survey_high_risk.md
            003__the_whole_call__complete_survey_high_risk.json

One file per test case, grouped by the module it came from and numbered in run
order. That way a single conversation can be opened, read, sent to somebody or
diffed against the same file from a previous run without going through a
thousand-line combined transcript to find it.

Nothing here asserts. A test that fails still writes its files, and that is the
point: the transcript of a failure is the most useful thing in the directory.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from msat_flow.llm import timing

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = Path(os.getenv("MSAT_RESULTS_DIR") or REPO_ROOT / "results")

CALLER = "Caller"
MEMBER = "Member"

MARK = {"passed": "✓", "failed": "✗", "skipped": "–"}

_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class Exchange:
    """One caller turn, one member turn, and what the agent did with it."""

    scenario: str
    caller: str
    member: str
    decided: dict = field(default_factory=dict)
    expected: dict = field(default_factory=dict)
    reply: str = ""
    took_s: float = 0.0  # this turn alone
    at_s: float = 0.0  # where it fell in the test, for lining two runs up
    # Every provider call this turn made, in order, each labelled with the role
    # it played: ``[{"role": "guard", "seconds": 0.41, "ok": true}, ...]``. The
    # sum of these against ``took_s`` is how much of the wait was the provider.
    calls: list[dict] = field(default_factory=list)

    @property
    def calls_s(self) -> float:
        return sum(call["seconds"] for call in self.calls)


@dataclass
class Conversation:
    """Every exchange one test produced, and how it ended."""

    test: str
    exchanges: list[Exchange] = field(default_factory=list)
    outcome: str = "not run"
    index: int = 0
    path: Path | None = None

    @property
    def failed(self) -> bool:
        return self.outcome == "failed"

    @property
    def calls(self) -> list[timing.Call]:
        """Every provider call this conversation made, in order."""
        return [
            timing.Call(call["role"], call["seconds"], call.get("ok", True))
            for exchange in self.exchanges
            for call in exchange.calls
        ]


def _compact(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def _roles(calls: list[timing.Call]) -> str:
    """``guard 0.41s · extract 1.12s · generate 1.83s`` — one role per call kind."""
    return " · ".join(
        f"{role} {stats.total_s:.2f}s" + (f" ×{stats.count}" if stats.count > 1 else "")
        for role, stats in timing.summarise(calls).items()
    )


def _parts(nodeid: str) -> tuple[str, str]:
    """A node id split into the module it lives in and a filename stem.

    ``tests/live/test_full_calls.py::test_the_whole_call[complete_survey]``
    becomes ``("test_full_calls", "the_whole_call__complete_survey")``.
    """
    path, _, rest = nodeid.partition("::")
    module = Path(path).stem or "tests"
    rest = rest.replace("[", "__").replace("]", "").removeprefix("test_")
    return _UNSAFE.sub("_", module), _UNSAFE.sub("_", rest).strip("_") or "test"


class Recorder:
    """Collects conversations and writes each one out as it completes."""

    def __init__(self) -> None:
        self.conversations: dict[str, Conversation] = {}
        self.started = datetime.now(timezone.utc)
        self.context: dict[str, str] = {}
        self._directory: Path | None = None
        self._written = 0

    # ── collecting ───────────────────────────────────────────────────────

    def conversation(self, test: str) -> Conversation:
        return self.conversations.setdefault(test, Conversation(test=test))

    # ── where it goes ────────────────────────────────────────────────────

    @property
    def directory(self) -> Path:
        """The run's directory, created on first write rather than at startup.

        A session where every test skips should leave nothing behind at all.
        """
        if self._directory is None:
            stamp = self.started.strftime("%Y-%m-%dT%H-%M-%SZ")
            self._directory = RESULTS_DIR / "live" / stamp
            self._directory.mkdir(parents=True, exist_ok=True)
            self._point_latest_here()
            self._start_index()
        return self._directory

    def _point_latest_here(self) -> None:
        """``results/live/latest`` follows the newest run."""
        latest = RESULTS_DIR / "live" / "latest"
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(self._directory.name, target_is_directory=True)
        except OSError:
            # Filesystems without symlinks still get a pointer they can read.
            (RESULTS_DIR / "live" / "latest.txt").write_text(
                f"{self._directory}\n", encoding="utf-8"
            )

    # ── writing ──────────────────────────────────────────────────────────

    def _start_index(self) -> None:
        context = " · ".join(f"**{key}** {value}" for key, value in self.context.items())
        (self._directory / "index.md").write_text(
            "\n".join(
                [
                    f"# Live run — {self.started.strftime('%Y-%m-%d %H:%M UTC')}",
                    "",
                    context or "_no context_",
                    "",
                    "Written as the run goes. A row appears here the moment its test finishes,",
                    "so an interrupted run still accounts for everything it got through.",
                    "",
                    "The three role columns are what that test spent in each of the provider",
                    "calls a turn can make — the guard call, the extraction call, and the line",
                    "the agent speaks. Per-role percentiles for the whole run are at the bottom.",
                    "",
                    "| # | | test | turns | slowest turn | guard | extract | generate | transcript |",
                    "|---:|:-:|---|---:|---:|---:|---:|---:|---|",
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def complete(self, test: str, outcome: str) -> Path | None:
        """Stamp a test's outcome and write its files now.

        Called as each test finishes rather than at the end of the session.
        """
        conversation = self.conversations.get(test)
        if conversation is None or conversation.path is not None:
            return None
        conversation.outcome = outcome

        self._written += 1
        conversation.index = self._written
        module, stem = _parts(test)
        folder = self.directory / module
        folder.mkdir(parents=True, exist_ok=True)
        conversation.path = folder / f"{conversation.index:03d}__{stem}.md"

        conversation.path.write_text(self._markdown(conversation), encoding="utf-8")
        conversation.path.with_suffix(".json").write_text(
            json.dumps(self._record(conversation), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self._append_index_row(conversation)
        self._append_jsonl(conversation)
        return conversation.path

    def _append_index_row(self, conversation: Conversation) -> None:
        relative = conversation.path.relative_to(self.directory)
        timed = [turn.took_s for turn in conversation.exchanges if turn.took_s]
        # The slowest turn, not the total: what matters on a call is whether any
        # single turn left the member listening to silence.
        slowest = f"{max(timed):.2f}s" if timed else "—"
        stats = timing.summarise(conversation.calls)
        per_role = "".join(
            f" {stats[role].total_s:.2f}s |" if role in stats else " — |" for role in timing.ROLES
        )
        row = (
            f"| {conversation.index} | {MARK.get(conversation.outcome, '?')} "
            f"| `{conversation.test}` | {len(conversation.exchanges)} | {slowest} "
            f"|{per_role} [{relative.name}]({relative}) |\n"
        )
        with (self.directory / "index.md").open("a", encoding="utf-8") as handle:
            handle.write(row)

    def _append_jsonl(self, conversation: Conversation) -> None:
        with (self.directory / "run.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self._record(conversation), ensure_ascii=False, default=str) + "\n")

    def _record(self, conversation: Conversation) -> dict:
        calls = conversation.calls
        return {
            "test": conversation.test,
            "outcome": conversation.outcome,
            "index": conversation.index,
            "started": self.started.isoformat(),
            "context": self.context,
            # Per-role totals for this test, so a baseline can be rebuilt from
            # run.jsonl alone without re-reading every exchange.
            "timings": {role: stats.as_dict() for role, stats in timing.summarise(calls).items()},
            "turn_total_s": round(sum(turn.took_s for turn in conversation.exchanges), 3),
            "calls_total_s": round(sum(call.seconds for call in calls), 3),
            "exchanges": [asdict(exchange) for exchange in conversation.exchanges],
        }

    def _markdown(self, conversation: Conversation) -> str:
        mark = MARK.get(conversation.outcome, "?")
        turns = conversation.exchanges
        lines = [
            f"# {mark} {conversation.test}",
            "",
            " · ".join(f"**{key}** {value}" for key, value in self.context.items()) or "_no context_",
            "",
            f"{len(turns)} turns — **{conversation.outcome}**{self._timing(turns)}",
            "",
            *self._role_lines(conversation),
            "---",
            "",
        ]
        for number, exchange in enumerate(turns, start=1):
            lines += self._exchange_lines(number, exchange)
        return "\n".join(lines)

    @staticmethod
    def _timing(turns: list[Exchange]) -> str:
        """Slowest turn first — the one a member would have noticed."""
        timed = [turn.took_s for turn in turns if turn.took_s]
        if not timed:
            return ""
        return f" · slowest turn {max(timed):.2f}s · whole call {sum(timed):.2f}s"

    @staticmethod
    def _role_lines(conversation: Conversation) -> list[str]:
        """Where this test's time went, by the role each provider call played.

        The share is against the turn time rather than against the provider time,
        so the three add up to less than 100% and what is left over — the
        planner, the normalisers, the test's own driving — is visible as the gap
        rather than being divided up among the calls.
        """
        calls = conversation.calls
        if not calls:
            return []
        turn_total = sum(turn.took_s for turn in conversation.exchanges)
        # Same columns, same order as the run's baseline at the foot of index.md,
        # so one test can be read against the run without re-reading the header.
        rows = [
            "| role | calls | p50 | p95 | slowest | total | share of turn time |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for role, stats in timing.summarise(calls).items():
            share = f"{stats.total_s / turn_total:.0%}" if turn_total else "—"
            failed = f" ({stats.failures} failed)" if stats.failures else ""
            rows.append(
                f"| {role}{failed} | {stats.count} | {stats.p50_s:.2f}s | {stats.p95_s:.2f}s "
                f"| {stats.slowest_s:.2f}s | {stats.total_s:.2f}s | {share} |"
            )
        return [*rows, ""]

    @staticmethod
    def _exchange_lines(number: int, exchange: Exchange) -> list[str]:
        took = f" · {exchange.took_s:.2f}s" if exchange.took_s else ""
        if exchange.calls:
            took += f" ({exchange.calls_s:.2f}s in {len(exchange.calls)} model calls)"
        lines = [f"**{number}. {exchange.scenario}**{took}", ""]
        if exchange.caller:
            lines += [f"> **{CALLER}** — {exchange.caller}", ">"]
        lines += [f"> **{MEMBER}** — {exchange.member}", ""]
        if exchange.reply:
            lines += [f"> **{CALLER}** — {exchange.reply}", ""]
        if exchange.expected:
            lines += [f"- expected: `{_compact(exchange.expected)}`"]
        if exchange.decided:
            lines += [f"- decided: `{_compact(exchange.decided)}`"]
        if exchange.calls:
            spent = " · ".join(
                f"{call['role']} {call['seconds']:.2f}s" + ("" if call.get("ok", True) else " (failed)")
                for call in exchange.calls
            )
            lines += [f"- calls: {spent}"]
        lines += [""]
        return lines

    # ── the end ──────────────────────────────────────────────────────────

    def finish(self) -> Path | None:
        """Close the index with a tally and the run's latency baseline."""
        if self._directory is None:
            return None
        written = [c for c in self.conversations.values() if c.path is not None]
        tally: dict[str, int] = {}
        for conversation in written:
            tally[conversation.outcome] = tally.get(conversation.outcome, 0) + 1
        failed = [c for c in written if c.failed]

        lines = ["", "", f"**{len(written)} conversations** — " + ", ".join(
            f"{count} {name}" for name, count in sorted(tally.items())
        ) or "nothing ran", ""]
        lines += self._baseline(written)
        if failed:
            lines += ["## Failures", "", "The transcripts worth reading first.", ""]
            lines += [
                f"- [`{c.test}`]({c.path.relative_to(self._directory)})" for c in failed
            ]
            lines += [""]
        with (self._directory / "index.md").open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        self._write_baseline_json(written)
        return self._directory

    # ── the baseline ─────────────────────────────────────────────────────
    #
    # The whole run's latency, by the role each provider call played. This is the
    # number that decides what is worth optimising: a turn whose time is nearly
    # all in `generate` is a different problem from one paying for three calls.

    def _baseline(self, written: list[Conversation]) -> list[str]:
        calls = [call for conversation in written for call in conversation.calls]
        if not calls:
            return []
        stats = timing.summarise(calls)
        turn_total = sum(
            turn.took_s for conversation in written for turn in conversation.exchanges
        )
        turns = sum(len(conversation.exchanges) for conversation in written)

        lines = [
            "## Latency baseline",
            "",
            f"{len(calls)} provider calls across {turns} turns. "
            f"p50 and p95 are per call; the share is that role's total against the "
            f"{turn_total:.1f}s the turns took end to end, so what the three leave over is "
            f"everything that is not the provider.",
            "",
            "| role | calls | p50 | p95 | slowest | total | share of turn time |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for role, role_stats in stats.items():
            share = f"{role_stats.total_s / turn_total:.0%}" if turn_total else "—"
            failed = f" ({role_stats.failures} failed)" if role_stats.failures else ""
            lines.append(
                f"| {role}{failed} | {role_stats.count} | {role_stats.p50_s:.2f}s "
                f"| {role_stats.p95_s:.2f}s | {role_stats.slowest_s:.2f}s "
                f"| {role_stats.total_s:.2f}s | {share} |"
            )
        provider_total = sum(call.seconds for call in calls)
        provider_share = f"{provider_total / turn_total:.0%}" if turn_total else "—"
        lines += [
            f"| **all calls** | {len(calls)} | | | | {provider_total:.2f}s | {provider_share} |",
            "",
            f"Mean turn: {turn_total / turns:.2f}s over {turns} turns.",
            "",
        ]
        return lines

    def headline(self) -> str:
        """One line of the baseline, for the terminal at the end of a run."""
        written = [c for c in self.conversations.values() if c.path is not None]
        calls = [call for conversation in written for call in conversation.calls]
        if not calls:
            return ""
        turn_total = sum(turn.took_s for conversation in written for turn in conversation.exchanges)
        return " · ".join(
            f"{role} p50 {stats.p50_s:.2f}s p95 {stats.p95_s:.2f}s"
            + (f" ({stats.total_s / turn_total:.0%})" if turn_total else "")
            for role, stats in timing.summarise(calls).items()
        )

    def _write_baseline_json(self, written: list[Conversation]) -> None:
        """The same numbers as data, for comparing two runs without parsing markdown."""
        calls = [call for conversation in written for call in conversation.calls]
        if not calls:
            return
        turns = [turn for conversation in written for turn in conversation.exchanges]
        turn_total = sum(turn.took_s for turn in turns)
        (self._directory / "baseline.json").write_text(
            json.dumps(
                {
                    "started": self.started.isoformat(),
                    "context": self.context,
                    "tests": len(written),
                    "turns": len(turns),
                    "turn_total_s": round(turn_total, 3),
                    "turn_p50_s": round(timing.percentile([t.took_s for t in turns], 0.50), 3),
                    "turn_p95_s": round(timing.percentile([t.took_s for t in turns], 0.95), 3),
                    "calls": len(calls),
                    "calls_total_s": round(sum(call.seconds for call in calls), 3),
                    "roles": {
                        role: {
                            **stats.as_dict(),
                            "share_of_turn_time": (
                                round(stats.total_s / turn_total, 4) if turn_total else None
                            ),
                        }
                        for role, stats in timing.summarise(calls).items()
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )


class TestTranscript:
    """The handle a single test writes through."""

    __slots__ = ("_conversation", "_t0", "_previous", "_timeline")

    def __init__(self, conversation: Conversation, timeline: timing.Timeline | None = None) -> None:
        self._conversation = conversation
        self._t0 = self._previous = time.monotonic()
        # Provider calls are drained per exchange, so each turn carries the calls
        # it made rather than the test carrying one undifferentiated pile.
        self._timeline = timeline

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
        """Record one exchange, timed on its own.

        ``took_s`` is how long THIS turn took — the gap since the previous
        exchange was recorded, which on a whole call is one agent turn and its
        model calls, and on a single-turn test is the one round trip. That is the
        number worth reading: a call is a conversation with a person waiting on
        the other end, and the question is always whether any one turn left them
        listening to silence, not what the run added up to.

        ``at_s`` keeps the offset into the test, so two runs of the same scenario
        can still be lined up turn for turn.

        ``calls`` is every provider call made since the previous exchange, each
        labelled with the role it played. That is what turns "this turn took 2.4
        seconds" into something actionable: which of the turn's three calls the
        member was actually waiting on.
        """
        now = time.monotonic()
        self._conversation.exchanges.append(
            Exchange(
                scenario=scenario,
                caller=caller,
                member=member,
                decided=decided or {},
                expected=expected or {},
                reply=reply,
                took_s=round(now - self._previous, 3),
                at_s=round(now - self._t0, 3),
                calls=[call.as_dict() for call in self._timeline.drain()] if self._timeline else [],
            )
        )
        self._previous = now
