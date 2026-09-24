"""Runtime settings, read from the environment (and ``.env`` when present)."""

from __future__ import annotations

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class E24Settings(BaseSettings):
    """How to reach Expert24's TraversalService.

    Timeouts are sized for a voice call: the member is waiting in silence while
    each request is in flight, so a slow Expert24 must fail fast rather than
    hold the line for the reference script's sixty seconds.
    """

    model_config = SettingsConfigDict(env_prefix="E24_", env_file=".env", extra="ignore")

    base_url: str
    api_root: str = "/webbuilder/TraversalService"
    language: str = "MEMBER"

    connect_timeout: float = Field(default=3.0, gt=0)
    read_timeout: float = Field(default=8.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    backoff_base: float = Field(default=0.25, ge=0)
    verify_tls: bool = True

    @field_validator("base_url", "api_root")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")
