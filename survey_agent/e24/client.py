"""Async client for Expert24's direct TraversalService.

Five calls, one URL structure for every survey::

    start     POST /Member                                  -> TraversalHandles
    first     POST /First/{tid}/{mid}/{algo}/0?Language=... -> Step
    next      POST /Next/{tid}/{mid}/{algo}/{node}          -> Step
    previous  GET  /Previous/{tid}                          -> Step
    qa        GET  /QA/{tid}                                -> QAResult

Retries follow one rule: a request is retried only when it cannot have taken
effect twice. A connection that never opened, or a 502/503 from the proxy,
means nothing reached Expert24, so any call may go again. A timeout or a 504
after the request was sent may mean Expert24 already applied it; only ``qa``,
the one call that changes nothing, is retried then. Everything else raises
:class:`E24UncertainOutcome` so the engine can re-establish where the traversal
is instead of answering a question twice. ``previous`` is a GET but moves the
traversal back a node, so it counts as state-changing.

Nothing identifying is logged: no bodies, no member ids, only the operation,
status and timing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Mapping
from types import TracebackType
from typing import Any
from urllib.parse import quote

import httpx

from ..settings import E24Settings
from .adapter import (
    DefaultRequestBuilder,
    DefaultResponseAdapter,
    RequestBuilder,
    ResponseAdapter,
)
from .errors import (
    E24HTTPError,
    E24ProtocolError,
    E24Rejected,
    E24Unavailable,
    E24UncertainOutcome,
)
from .models import QAResult, Raw, Step, TraversalHandles

log = logging.getLogger(__name__)

# Nothing was sent, or nothing reached Expert24: safe to retry any call.
_NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
# Sent, outcome unknown.
_MAYBE_APPLIED = (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)
_PROXY_NOT_FORWARDED = frozenset({502, 503})
_PROXY_TIMED_OUT = 504
# Sent on every request, including on a caller-supplied http client. The control
# always sends JSON; the content type is what the server negotiates on.
_HEADERS = {"Content-Type": "application/json", "Accept": "application/json"}


def _esc(value: object) -> str:
    return quote(str(value), safe="")


class E24Client:
    def __init__(
        self,
        settings: E24Settings,
        *,
        http: httpx.AsyncClient | None = None,
        builder: RequestBuilder | None = None,
        adapter: ResponseAdapter | None = None,
        auth: httpx.Auth | None = None,
    ) -> None:
        self.settings = settings
        self.builder: RequestBuilder = builder or DefaultRequestBuilder()
        self.adapter: ResponseAdapter = adapter or DefaultResponseAdapter()
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(settings.read_timeout, connect=settings.connect_timeout),
            verify=settings.verify_tls,
            auth=auth,
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> E24Client:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    # -- the five calls ----------------------------------------------------

    async def start(
        self, member_id: str, prepop: Mapping[str, Any] | None = None
    ) -> TraversalHandles:
        payload = await self._request(
            "start", "POST", "/Member", body=self.builder.start_body(member_id, prepop)
        )
        return self.adapter.handles(payload)

    async def first(
        self, handles: TraversalHandles, algo_id: str, *, language: str | None = None
    ) -> Step:
        path = (
            f"/First/{_esc(handles.traversal_id)}/{_esc(handles.e24_member_id)}/{_esc(algo_id)}/0"
        )
        payload = await self._request(
            "first", "POST", path, query={"Language": language or self.settings.language}
        )
        return self.adapter.step(payload)

    async def next(
        self,
        handles: TraversalHandles,
        algo_id: str,
        node_id: str,
        answers: Mapping[str, str],
    ) -> Step:
        path = (
            f"/Next/{_esc(handles.traversal_id)}/{_esc(handles.e24_member_id)}"
            f"/{_esc(algo_id)}/{_esc(node_id)}"
        )
        payload = await self._request("next", "POST", path, body=self.builder.answer_body(answers))
        return self.adapter.step(payload)

    async def previous(self, traversal_id: str) -> Step:
        payload = await self._request("previous", "GET", f"/Previous/{_esc(traversal_id)}")
        return self.adapter.step(payload)

    async def qa(self, traversal_id: str) -> QAResult:
        payload = await self._request("qa", "GET", f"/QA/{_esc(traversal_id)}", read_only=True)
        return self.adapter.qa(payload)

    # -- plumbing ----------------------------------------------------------

    async def _request(
        self,
        operation: str,
        method: str,
        path: str,
        *,
        query: Mapping[str, str] | None = None,
        body: Raw | None = None,
        read_only: bool = False,
    ) -> Raw:
        url = f"{self.settings.base_url}{self.settings.api_root}{path}"
        # The control always sends a JSON body on POST, even the empty object.
        content = json.dumps(body if body is not None else {}) if method == "POST" else None
        attempts = self.settings.max_retries + 1

        for attempt in range(attempts):
            last = attempt == attempts - 1
            started = time.perf_counter()
            try:
                response = await self._http.request(
                    method, url, params=query, content=content, headers=_HEADERS
                )
            except _NOT_SENT as exc:
                if last:
                    raise E24Unavailable(
                        f"could not reach Expert24: {exc!r}", operation=operation
                    ) from exc
                await self._backoff(operation, attempt, reason=type(exc).__name__)
                continue
            except _MAYBE_APPLIED as exc:
                if not read_only:
                    raise E24UncertainOutcome(
                        f"{operation} was sent but no response arrived: {exc!r}",
                        operation=operation,
                    ) from exc
                if last:
                    raise E24Unavailable(
                        f"no response from Expert24: {exc!r}", operation=operation
                    ) from exc
                await self._backoff(operation, attempt, reason=type(exc).__name__)
                continue

            elapsed_ms = round((time.perf_counter() - started) * 1000)
            status = response.status_code
            log.info("e24 %s -> %s in %sms", operation, status, elapsed_ms)

            retryable = status in _PROXY_NOT_FORWARDED or (status == _PROXY_TIMED_OUT and read_only)
            if retryable and not last:
                await self._backoff(operation, attempt, reason=f"HTTP {status}")
                continue
            if status == _PROXY_TIMED_OUT and not read_only:
                raise E24UncertainOutcome(
                    f"{operation}: proxy timed out waiting for Expert24", operation=operation
                )
            if status in _PROXY_NOT_FORWARDED or (status == _PROXY_TIMED_OUT and read_only):
                raise E24Unavailable(
                    f"{operation}: HTTP {status} from the proxy", operation=operation
                )
            if status >= 400:
                raise E24HTTPError(
                    f"{operation}: HTTP {status}: {response.text[:200]}",
                    operation=operation,
                    status=status,
                )
            return self._parse(operation, response)

        raise AssertionError("unreachable")  # pragma: no cover

    def _parse(self, operation: str, response: httpx.Response) -> Raw:
        raw = response.text
        if not raw.strip():
            raise E24ProtocolError(
                f"{operation}: empty body (HTTP {response.status_code})", operation=operation
            )
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            hint = ""
            if raw.lstrip()[:15].lower().startswith(("<!doctype", "<html")):
                hint = " (an HTML page — base_url points at a website, not the API)"
            raise E24ProtocolError(
                f"{operation}: response is not JSON{hint}", operation=operation
            ) from exc
        if not isinstance(payload, dict):
            raise E24ProtocolError(f"{operation}: expected a JSON object", operation=operation)
        if reported := self.adapter.error(payload):
            raise E24Rejected(f"{operation}: Expert24 reported: {reported}", operation=operation)
        return payload

    async def _backoff(self, operation: str, attempt: int, *, reason: str) -> None:
        base = self.settings.backoff_base
        delay = base * (2**attempt) + random.uniform(0, base)
        log.warning("e24 %s retry %d after %s (%.2fs)", operation, attempt + 1, reason, delay)
        if delay:
            await asyncio.sleep(delay)
