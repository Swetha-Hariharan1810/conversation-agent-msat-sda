"""Opt-in gate for the live tests.

Everything under ``tests/live/`` talks to a real provider. That means real money,
real latency and a real chance of a flake, so nothing here runs unless somebody
asked for it:

    MSAT_LIVE_TESTS=1 uv run pytest tests/live -v

Without the flag the whole directory skips with the reason printed, rather than
erroring or — worse — passing quietly against a stub and being mistaken for
evidence that the prompts work.

Credentials come from the environment exactly as they do on a call, so a live run
exercises the same ``LLMClient`` the agent uses against the same deployment.
"""

from __future__ import annotations

import os

import pytest

from msat_flow.llm.client import LLMClient
from msat_flow.script.spec import load_spec

FLAG = "MSAT_LIVE_TESTS"
_TRUTHY = {"1", "true", "yes", "on"}


def _missing_credentials() -> list[str]:
    """What the configured provider needs from the environment and has not got."""
    provider = os.getenv("LLM_PROVIDER", "openai").lower()
    needed = (
        ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY")
        if provider.startswith("azure")
        else ("OPENAI_API_KEY",)
    )
    return [name for name in needed if not os.getenv(name)]


def pytest_runtest_setup(item: pytest.Item) -> None:
    if os.getenv(FLAG, "").strip().lower() not in _TRUTHY:
        pytest.skip(f"live tests are opt-in — set {FLAG}=1 to run them against a real provider")
    missing = _missing_credentials()
    if missing:
        pytest.skip(f"{FLAG} is set but the provider is not configured: missing {', '.join(missing)}")


@pytest.fixture(scope="session")
def client() -> LLMClient:
    """The same client the agent uses on a call, configured from the environment."""
    return LLMClient()


@pytest.fixture(scope="session")
def spec():
    return load_spec()
