"""Translation between Expert24 JSON and our models, in both directions.

The URL structure is the same for every survey; what may differ is the body we
send and the shape we get back. Both are behind a protocol here, with a default
that matches the direct TraversalService as the shipped assessment control
calls it (see ``docs/e24/``). A survey whose payload or response differs supplies
its own builder or adapter — usually by subclassing the default and overriding
one method — and the client and engine stay untouched.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping
from typing import Any, Protocol

from .errors import E24ProtocolError
from .models import (
    AnswerOption,
    Completion,
    Conclusion,
    QARecord,
    QAResult,
    Question,
    QuestionKind,
    Raw,
    Step,
    TraversalHandles,
)


class RequestBuilder(Protocol):
    def start_body(self, member_id: str, prepop: Mapping[str, Any] | None) -> Raw: ...

    def answer_body(self, answers: Mapping[str, str]) -> Raw: ...


class ResponseAdapter(Protocol):
    def error(self, payload: Raw) -> str | None: ...

    def handles(self, payload: Raw) -> TraversalHandles: ...

    def step(self, payload: Raw) -> Step: ...

    def qa(self, payload: Raw) -> QAResult: ...


class DefaultRequestBuilder:
    def start_body(self, member_id: str, prepop: Mapping[str, Any] | None) -> Raw:
        body: Raw = {"@UserID": member_id, "callback": "raw"}
        if prepop:
            body["Prepop"] = dict(prepop)
        return body

    def answer_body(self, answers: Mapping[str, str]) -> Raw:
        """Keys are option indices. A selected radio or checkbox carries the empty
        string; a typed answer carries its text: ``{"1": ""}``, ``{"1": "180"}``.
        """
        return {str(index): "" if value is None else str(value) for index, value in answers.items()}


_TAG = re.compile(r"<[^>]+>")
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?%)\]])")


def plain(text: Any) -> str:
    """Expert24 text carries HTML and entities; a voice line must not."""
    if not text:
        return ""
    # Tags become spaces so the words either side stay apart; that leaves a gap
    # before trailing punctuation, which the second pass closes.
    stripped = " ".join(html.unescape(_TAG.sub(" ", str(text))).split())
    return _SPACE_BEFORE_PUNCT.sub(r"\1", stripped)


def _kind(options: list[Raw]) -> QuestionKind:
    types = {str(o.get("ControlType") or "").lower() for o in options}
    if not options:
        return QuestionKind.NONE
    if "checkbox" in types:
        return QuestionKind.MULTI
    if "radio" in types:
        return QuestionKind.SINGLE
    return QuestionKind.VALUE


class DefaultResponseAdapter:
    def error(self, payload: Raw) -> str | None:
        err = payload.get("Error")
        return str(err) if err else None

    def handles(self, payload: Raw) -> TraversalHandles:
        table = payload.get("Table") or []
        if not table:
            raise E24ProtocolError(
                "start response carried no Table entry; the member id may be unknown "
                "in this environment or a required prepop value missing",
                operation="start",
            )
        row = table[0]
        traversal_id, member_id = row.get("TraversalID"), row.get("MemberID")
        if not traversal_id or not member_id:
            raise E24ProtocolError(
                "start response is missing TraversalID or MemberID", operation="start"
            )
        return TraversalHandles(traversal_id=str(traversal_id), e24_member_id=str(member_id))

    def is_complete(self, payload: Raw) -> bool:
        """A traversal is over when Expert24 reports or stops naming an algorithm."""
        return bool(payload.get("Report")) or not payload.get("AlgoName")

    def step(self, payload: Raw) -> Step:
        if self.is_complete(payload):
            return Completion(
                conclusions=tuple(
                    Conclusion(
                        category=str(c.get("Category") or ""),
                        text=plain(c.get("DisplayText")),
                        raw=c,
                    )
                    for c in payload.get("Conclusions") or []
                ),
                raw=payload,
            )
        questions = payload.get("Questions") or []
        node_id = payload.get("NodeID")
        if not questions or node_id is None:
            raise E24ProtocolError(
                "response names an algorithm but carries no question or NodeID",
                operation="step",
            )
        question = questions[0]
        answers: list[Raw] = list(question.get("Answers") or [])
        return Question(
            node_id=str(node_id),
            algo_id=str(payload.get("AlgoID") or ""),
            algo_name=str(payload.get("AlgoName") or ""),
            title=plain(question.get("Title")),
            text=plain(question.get("DisplayText")),
            kind=_kind(answers),
            options=tuple(
                AnswerOption(
                    index=str(a.get("Index")),
                    label=plain(a.get("DisplayText")),
                    control_type=str(a.get("ControlType") or ""),
                    subtype=str(a.get("ControlSubType") or ""),
                    raw=a,
                )
                for a in answers
            ),
            raw=payload,
        )

    def qa(self, payload: Raw) -> QAResult:
        return QAResult(
            records=tuple(
                QARecord(
                    question=plain(row.get("Question")),
                    answer=plain(row.get("Answer")),
                    value=plain(row.get("SValue")),
                    raw=row,
                )
                for row in payload.get("Table") or []
            ),
            raw=payload,
        )
