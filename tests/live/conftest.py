"""Opt-in gate for the live tests.

Everything under ``tests/live/`` talks to a real provider. That means real money,
real latency and a real chance of a flake, so nothing here runs unless somebody
asked for it:

    MSAT_LIVE_TESTS=1 uv run pytest tests/live -v

Without the flag the whole directory skips and says so, rather than erroring or —
worse — passing quietly against a stub and being mistaken for evidence that the
prompts work.

Credentials, and the ``.env`` file they usually live in, are handled in
``environment.py``; the skip messages below quote what it found so a directory
that skips entirely explains itself on the spot.
"""

from __future__ import annotations

import os

import pytest

from msat_flow.llm.client import LLMClient
from msat_flow.script.spec import load_spec

from . import environment as env
from .transcript import Recorder, TestTranscript


def pytest_runtest_setup(item: pytest.Item) -> None:
    if not env.enabled():
        pytest.skip(f"live tests are opt-in — set {env.FLAG}=1 to run them against a real provider")
    absent = env.missing()
    if absent:
        pytest.skip(
            f"{env.FLAG} is set, but LLM_PROVIDER={env.provider()!r} still needs "
            f"{', '.join(absent)}. Env file: {env.env_file_state()}."
        )


@pytest.fixture(scope="session")
def client() -> LLMClient:
    """The same client the agent uses on a call, configured from the environment."""
    return LLMClient()


@pytest.fixture(scope="session")
def spec():
    return load_spec()


# ── transcripts ──────────────────────────────────────────────────────────
#
# What was said is the run's real product; the pass/fail is a summary of it. The
# recorder is filled by the tests and written once at the end, so a run that is
# interrupted still leaves everything up to that point on disk.


@pytest.fixture(scope="session")
def recorder(client) -> Recorder:
    keeper = Recorder()
    keeper.context = {
        "provider": env.provider(),
        "model": os.getenv("MSAT_MODEL") or os.getenv("LLM_MODEL") or client.model,
        "repeats": os.getenv(env.REPEAT_VAR, "1"),
    }
    return keeper


@pytest.fixture
def transcript(recorder, request) -> TestTranscript:
    """Where a test writes what was said. One per test, keyed by node id."""
    return TestTranscript(recorder.conversation(request.node.nodeid))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Stamp each test's outcome onto its conversation.

    A failure's transcript is the most useful thing in the directory, so the
    outcome is recorded rather than the conversation dropped.
    """
    report = (yield).get_result()
    if report.when == "call":
        keeper = getattr(item.session, "_msat_recorder", None)
        if keeper is not None:
            keeper.outcome(item.nodeid, report.outcome)


def pytest_sessionfinish(session, exitstatus):
    keeper = getattr(session, "_msat_recorder", None)
    if keeper is None:
        return
    written = keeper.write()
    if written is not None:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.write_line(f"\nconversations written to {written}")


@pytest.fixture(scope="session", autouse=True)
def _publish_recorder(request, recorder):
    """Hand the recorder to the session so sessionfinish can write it out."""
    request.session._msat_recorder = recorder
    return recorder
