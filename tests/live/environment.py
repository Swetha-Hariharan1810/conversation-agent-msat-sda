"""Where the live tests get their credentials, and whether they have any.

Kept out of ``conftest.py`` so both the gate (``tests/live/conftest.py``) and the
header line (``tests/conftest.py``) can read the same answer. Importing a
conftest module to share code is a way to get two of them.

## The .env line is load-bearing

``langgraph.json`` points at ``.env`` and the LangGraph server reads it, so
nothing in this project ever had to load it itself. Under bare ``pytest``
nothing does — and a gate built on ``os.getenv`` then reports "no credentials"
to somebody who is looking straight at their credentials. So the file is loaded
here, before anything is checked, and what happened to it is reported either way.

Exported variables win over the file: overriding a ``.env`` for one run is the
whole point of exporting something.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

FLAG = "MSAT_LIVE_TESTS"
ENV_FILE_VAR = "MSAT_ENV_FILE"
REPEAT_VAR = "MSAT_LIVE_REPEAT"

_TRUTHY = {"1", "true", "yes", "on"}

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = Path(os.getenv(ENV_FILE_VAR) or REPO_ROOT / ".env")

_LOADED = load_dotenv(ENV_FILE, override=False) if ENV_FILE.is_file() else False


def provider() -> str:
    return os.getenv("LLM_PROVIDER", "openai")


def required() -> tuple[str, ...]:
    """What the configured provider needs before a call can even be attempted.

    OPENAI_API_VERSION is required for Azure deliberately: AzureChatOpenAI
    without one fails at call time with an error about the deployment, which
    sends you looking in the wrong place entirely.
    """
    if provider().lower().startswith("azure"):
        return ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "OPENAI_API_VERSION")
    return ("OPENAI_API_KEY",)


def missing() -> list[str]:
    return [name for name in required() if not os.getenv(name)]


def enabled() -> bool:
    return os.getenv(FLAG, "").strip().lower() in _TRUTHY


def env_file_state() -> str:
    if _LOADED:
        return f"loaded {ENV_FILE}"
    if ENV_FILE.is_file():
        return f"{ENV_FILE} exists but set nothing"
    return f"no env file at {ENV_FILE} (set {ENV_FILE_VAR} to point elsewhere)"


def summary() -> str:
    """One line saying what the gate found, so a full skip is never a mystery."""
    return (
        f"live tests: {FLAG}={'on' if enabled() else 'off'}, provider={provider()}, "
        f"{env_file_state()}, missing={missing() or 'nothing'}"
    )
