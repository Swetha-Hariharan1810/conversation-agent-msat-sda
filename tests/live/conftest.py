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

import pytest

from msat_flow.llm.client import LLMClient
from msat_flow.script.spec import load_spec

from . import environment as env


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
