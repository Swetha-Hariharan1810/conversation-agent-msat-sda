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
    elapsed_s: float = 0.0


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


def _compact(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


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
                    "| # | | test | turns | transcript |",
                    "|---:|:-:|---|---:|---|",
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
        row = (
            f"| {conversation.index} | {MARK.get(conversation.outcome, '?')} "
            f"| `{conversation.test}` | {len(conversation.exchanges)} | [{relative.name}]({relative}) |\n"
        )
        with (self.directory / "index.md").open("a", encoding="utf-8") as handle:
            handle.write(row)

    def _append_jsonl(self, conversation: Conversation) -> None:
        with (self.directory / "run.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(self._record(conversation), ensure_ascii=False, default=str) + "\n")

    def _record(self, conversation: Conversation) -> dict:
        return {
            "test": conversation.test,
            "outcome": conversation.outcome,
            "index": conversation.index,
            "started": self.started.isoformat(),
            "context": self.context,
            "exchanges": [asdict(exchange) for exchange in conversation.exchanges],
        }

    def _markdown(self, conversation: Conversation) -> str:
        mark = MARK.get(conversation.outcome, "?")
        lines = [
            f"# {mark} {conversation.test}",
            "",
            " · ".join(f"**{key}** {value}" for key, value in self.context.items()) or "_no context_",
            "",
            f"{len(conversation.exchanges)} exchanges — **{conversation.outcome}**",
            "",
            "---",
            "",
        ]
        for exchange in conversation.exchanges:
            lines += self._exchange_lines(exchange)
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

    # ── the end ──────────────────────────────────────────────────────────

    def finish(self) -> Path | None:
        """Close the index with a tally. Everything else is already on disk."""
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
        if failed:
            lines += ["## Failures", "", "The transcripts worth reading first.", ""]
            lines += [
                f"- [`{c.test}`]({c.path.relative_to(self._directory)})" for c in failed
            ]
            lines += [""]
        with (self._directory / "index.md").open("a", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        return self._directory


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
