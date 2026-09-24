"""E24Client against a fake TraversalService (httpx.MockTransport).

The fixture is the MSAT UAT run from docs/e24/, so the happy path here is the
same sequence of requests the reference script sent.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from survey_agent.e24 import (
    Completion,
    DefaultResponseAdapter,
    E24Client,
    E24HTTPError,
    E24ProtocolError,
    E24Rejected,
    E24Unavailable,
    E24UncertainOutcome,
    Question,
    QuestionKind,
    TraversalHandles,
)
from survey_agent.settings import E24Settings

WALK = json.loads((Path(__file__).parent / "fixtures/msat_10657/walk.json").read_text())
BASE = "https://e24.test"
ROOT = "/webbuilder/TraversalService"
HANDLES = TraversalHandles(
    traversal_id=WALK["start"]["Table"][0]["TraversalID"],
    e24_member_id=WALK["start"]["Table"][0]["MemberID"],
)

Handler = Callable[[httpx.Request], httpx.Response]


def make_client(handler: Handler, **overrides: object) -> E24Client:
    settings = E24Settings(base_url=BASE + "/", backoff_base=0, **overrides)  # type: ignore[arg-type]
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return E24Client(settings, http=http)


def fake_service(sent: list[httpx.Request]) -> Handler:
    """Serves the recorded walk, checking each /Next body against the recording."""
    by_node = {str(step["node"]): step for step in WALK["next"]}

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        path = request.url.path.removeprefix(ROOT)
        if path == "/Member":
            return httpx.Response(200, json=WALK["start"])
        if path.startswith("/First/"):
            return httpx.Response(200, json=WALK["first"])
        if path.startswith("/Next/"):
            step = by_node[path.rsplit("/", 1)[1]]
            assert json.loads(request.content) == step["body"]
            return httpx.Response(200, json=step["response"])
        if path.startswith("/QA/"):
            return httpx.Response(200, json=WALK["qa"])
        return httpx.Response(404)

    return handler


# -- the happy path ----------------------------------------------------------


async def test_whole_traversal_matches_the_recorded_run() -> None:
    sent: list[httpx.Request] = []
    async with make_client(fake_service(sent)) as client:
        handles = await client.start("ABC_TMJarrett")
        assert handles == HANDLES

        step = await client.first(handles, "10657")
        visited = []
        for recorded in WALK["next"]:
            assert isinstance(step, Question)
            visited.append(step.node_id)
            step = await client.next(handles, step.algo_id, step.node_id, recorded["body"])
        assert isinstance(step, Completion)
        assert step.conclusions[0].text == "2026.03.13.1"

        qa = await client.qa(handles.traversal_id)

    assert visited == [str(s["node"]) for s in WALK["next"]]
    assert len(qa.records) == 10
    assert qa.records[3].value == "dscvds"
    assert qa.records[0].answer == "Next >"  # entity decoded

    first = sent[1]
    assert first.method == "POST"
    assert first.url.path == f"{ROOT}/First/{HANDLES.traversal_id}/{HANDLES.e24_member_id}/10657/0"
    assert first.url.params["Language"] == "MEMBER"
    assert first.content == b"{}"
    assert first.headers["content-type"] == "application/json"


async def test_start_sends_user_id_and_prepop_only_when_given() -> None:
    sent: list[httpx.Request] = []
    async with make_client(fake_service(sent)) as client:
        await client.start("M1")
        await client.start("M1", {"RiskLevel": "3"})
    assert json.loads(sent[0].content) == {"@UserID": "M1", "callback": "raw"}
    assert json.loads(sent[1].content) == {
        "@UserID": "M1",
        "callback": "raw",
        "Prepop": {"RiskLevel": "3"},
    }


async def test_previous_is_a_get_on_the_traversal_only() -> None:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json=WALK["next"][0]["response"])

    async with make_client(handler) as client:
        step = await client.previous(HANDLES.traversal_id)
    assert isinstance(step, Question) and step.node_id == "908"
    assert sent[0].method == "GET"
    assert sent[0].url.path == f"{ROOT}/Previous/{HANDLES.traversal_id}"


async def test_ids_are_escaped_in_the_path() -> None:
    sent: list[httpx.Request] = []
    async with make_client(fake_service(sent)) as client:
        await client.qa("a/b c")
    assert sent[0].url.raw_path.decode() == f"{ROOT}/QA/a%2Fb%20c"


# -- reading questions -------------------------------------------------------


def question_at(node: int) -> Question:
    for step in WALK["next"]:
        if step["response"].get("NodeID") == node:
            result = DefaultResponseAdapter().step(step["response"])
            assert isinstance(result, Question)
            return result
    raise KeyError(node)


def test_question_kinds_and_options() -> None:
    radio = question_at(908)
    assert radio.kind is QuestionKind.SINGLE
    assert [(o.index, o.label) for o in radio.options] == [("1", "Yes"), ("2", "No")]

    typed = question_at(903)
    assert typed.kind is QuestionKind.VALUE
    assert typed.options[0].subtype == "text"
    # tags stripped, entities decoded, no gap left before punctuation
    assert "don’t have feedback, please enter no or none." in typed.text

    speak_only = question_at(876)
    assert speak_only.kind is QuestionKind.NONE and speak_only.options == ()


def test_checkbox_is_multi() -> None:
    payload = {
        "AlgoID": 1,
        "AlgoName": "x",
        "NodeID": 5,
        "Questions": [
            {
                "DisplayText": "Pick any",
                "Answers": [
                    {"Index": "1", "DisplayText": "A", "ControlType": "checkbox"},
                    {"Index": "2", "DisplayText": "B", "ControlType": "checkbox"},
                ],
            }
        ],
    }
    step = DefaultResponseAdapter().step(payload)
    assert isinstance(step, Question) and step.kind is QuestionKind.MULTI


def test_unknown_fields_are_kept_raw() -> None:
    payload = {**WALK["first"], "SomethingNew": {"x": 1}}
    step = DefaultResponseAdapter().step(payload)
    assert step.raw["SomethingNew"] == {"x": 1}


# -- failures ----------------------------------------------------------------


def respond(*responses: httpx.Response | Exception) -> tuple[Handler, list[httpx.Request]]:
    sent: list[httpx.Request] = []
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return handler, sent


async def test_start_without_table_is_a_protocol_error() -> None:
    handler, _ = respond(httpx.Response(200, json={"Table": []}))
    async with make_client(handler) as client:
        with pytest.raises(E24ProtocolError, match="no Table"):
            await client.start("M1")


async def test_error_in_body_is_rejected() -> None:
    handler, _ = respond(httpx.Response(200, json={"Error": "Invalid traversal"}))
    async with make_client(handler) as client:
        with pytest.raises(E24Rejected, match="Invalid traversal"):
            await client.first(HANDLES, "10657")


async def test_html_page_is_explained() -> None:
    handler, _ = respond(httpx.Response(200, text="<!DOCTYPE html><html></html>"))
    async with make_client(handler) as client:
        with pytest.raises(E24ProtocolError, match="HTML page"):
            await client.qa("t")


async def test_empty_body_is_a_protocol_error() -> None:
    handler, _ = respond(httpx.Response(200, text="  "))
    async with make_client(handler) as client:
        with pytest.raises(E24ProtocolError, match="empty body"):
            await client.qa("t")


async def test_client_error_status_is_not_retried() -> None:
    handler, sent = respond(httpx.Response(500, text="boom"))
    async with make_client(handler) as client:
        with pytest.raises(E24HTTPError) as info:
            await client.next(HANDLES, "10657", "908", {"1": ""})
    assert info.value.status == 500 and len(sent) == 1


async def test_connection_failure_is_retried_for_a_write() -> None:
    handler, sent = respond(
        httpx.ConnectError("refused"), httpx.Response(200, json=WALK["next"][0]["response"])
    )
    async with make_client(handler) as client:
        step = await client.next(HANDLES, "10657", "487", {})
    assert isinstance(step, Question) and len(sent) == 2


async def test_proxy_not_forwarding_is_retried_then_unavailable() -> None:
    handler, sent = respond(*(httpx.Response(503) for _ in range(3)))
    async with make_client(handler, max_retries=2) as client:
        with pytest.raises(E24Unavailable):
            await client.start("M1")
    assert len(sent) == 3


async def test_timeout_on_next_is_uncertain_and_never_resent() -> None:
    handler, sent = respond(httpx.ReadTimeout("slow"))
    async with make_client(handler) as client:
        with pytest.raises(E24UncertainOutcome):
            await client.next(HANDLES, "10657", "908", {"1": ""})
    assert len(sent) == 1


async def test_proxy_timeout_on_next_is_uncertain() -> None:
    handler, sent = respond(httpx.Response(504))
    async with make_client(handler) as client:
        with pytest.raises(E24UncertainOutcome):
            await client.next(HANDLES, "10657", "908", {"1": ""})
    assert len(sent) == 1


async def test_timeout_on_previous_is_uncertain() -> None:
    handler, sent = respond(httpx.ReadTimeout("slow"))
    async with make_client(handler) as client:
        with pytest.raises(E24UncertainOutcome):
            await client.previous("t")
    assert len(sent) == 1


async def test_timeout_on_qa_is_retried() -> None:
    handler, sent = respond(
        httpx.ReadTimeout("slow"), httpx.Response(504), httpx.Response(200, json=WALK["qa"])
    )
    async with make_client(handler, max_retries=2) as client:
        qa = await client.qa("t")
    assert len(qa.records) == 10 and len(sent) == 3


def test_settings_require_a_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("E24_BASE_URL", raising=False)
    with pytest.raises(ValueError):
        E24Settings(_env_file=None)  # type: ignore[call-arg]
