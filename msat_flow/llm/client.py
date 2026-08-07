"""Thin structured-output client.

Kept deliberately small: the agent depends on ``structured()`` and ``text()`` and
nothing else, so tests can pass a scripted stub and the whole conversation runs
without a provider.

Provider comes from the environment, matching the RCM repos' ``.env``:

    LLM_PROVIDER=azure_openai        # or "openai"
    LLM_MODEL=gpt-5.4-mini
    AZURE_OPENAI_DEPLOYMENT=...      # Azure deployment name (defaults to LLM_MODEL)
    AZURE_OPENAI_ENDPOINT=...
    AZURE_OPENAI_API_KEY=...
    OPENAI_API_VERSION=...
"""

from __future__ import annotations

import os
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


def _env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return default


class SupportsStructured(Protocol):
    async def structured(self, messages: list[dict[str, str]], schema: type[ModelT]) -> ModelT: ...

    async def text(self, messages: list[dict[str, str]]) -> str: ...


class LLMClient:
    """Structured + free-text calls against an OpenAI or Azure OpenAI chat model."""

    def __init__(
        self,
        model: str | None = None,
        temperature: float | None = None,
        provider: str | None = None,
    ):
        self.provider = (provider or _env("LLM_PROVIDER", default="openai")).lower()
        self.model = model or _env("MSAT_MODEL", "LLM_MODEL", default="gpt-4o-mini")
        self.temperature = (
            float(_env("MSAT_TEMPERATURE", default="0")) if temperature is None else temperature
        )
        # Provider 429s are routine on shared deployments and must not end a live
        # call. The SDK backs off between attempts.
        self.max_retries = int(_env("LLM_MAX_RETRIES", default="6"))
        # The SDK's default request timeout is ten minutes, which on a live call
        # is indistinguishable from a hang — the member sits in silence and the
        # turn never returns. Fail fast enough to retry inside a human pause.
        self.timeout = float(_env("LLM_TIMEOUT_SECONDS", default="45"))
        self._chat: Any | None = None

    def _http_client(self):
        """An HTTP client whose idle connections expire rather than rot."""
        import httpx

        return httpx.AsyncClient(
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=5, keepalive_expiry=15.0),
            timeout=self.timeout,
        )

    def _client(self):
        if self._chat is not None:
            return self._chat
        if self.provider.startswith("azure"):
            from langchain_openai import AzureChatOpenAI

            self._chat = AzureChatOpenAI(
                azure_deployment=_env("AZURE_OPENAI_DEPLOYMENT", default=self.model),
                api_version=_env("OPENAI_API_VERSION", "AZURE_OPENAI_API_VERSION"),
                temperature=self.temperature,
                max_retries=self.max_retries,
                timeout=self.timeout,
                http_async_client=self._http_client(),
            )
        else:
            from langchain_openai import ChatOpenAI

            self._chat = ChatOpenAI(
                model=self.model,
                temperature=self.temperature,
                max_retries=self.max_retries,
                timeout=self.timeout,
                http_async_client=self._http_client(),
            )
        return self._chat

    async def structured(self, messages: list[dict[str, str]], schema: type[ModelT]) -> ModelT:
        # Function calling rather than strict json_schema mode: Azure's strict
        # mode demands every property be listed in `required`, which would force
        # the model to emit a value for each optional field — exactly the
        # guessing the extraction contract forbids.
        chain = self._client().with_structured_output(schema, method="function_calling")
        result = await chain.ainvoke(messages)
        return result if isinstance(result, schema) else schema.model_validate(result)

    async def text(self, messages: list[dict[str, str]]) -> str:
        response = await self._client().ainvoke(messages)
        return str(getattr(response, "content", response)).strip()
