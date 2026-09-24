"""Our own view of an Expert24 traversal.

The engine only ever sees these models, never raw Expert24 JSON, so a change in
the response shape is absorbed by an adapter (``adapter.py``) and nowhere else.
Every model keeps the ``raw`` payload it was read from: nothing Expert24 sends
is lost, even when no field here names it yet.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

Raw = dict[str, Any]


class _Model(BaseModel):
    model_config = ConfigDict(frozen=True)


class TraversalHandles(_Model):
    """The two ids every call after ``Member`` needs."""

    traversal_id: str
    e24_member_id: str


class QuestionKind(StrEnum):
    SINGLE = "single"  # radio: exactly one option
    MULTI = "multi"  # checkbox: one or more options
    VALUE = "value"  # typed entry: free text, a number, a date
    NONE = "none"  # nothing to answer: speak it and continue


class AnswerOption(_Model):
    index: str
    label: str
    control_type: str = ""
    subtype: str = ""
    raw: Raw = Field(default_factory=dict, repr=False)


class Question(_Model):
    """One node of a traversal, as it should be put to the member."""

    node_id: str
    algo_id: str
    algo_name: str
    text: str
    title: str = ""
    kind: QuestionKind
    options: tuple[AnswerOption, ...] = ()
    raw: Raw = Field(default_factory=dict, repr=False)

    def option(self, index: str) -> AnswerOption | None:
        return next((o for o in self.options if o.index == index), None)


class Conclusion(_Model):
    category: str
    text: str
    raw: Raw = Field(default_factory=dict, repr=False)


class Completion(_Model):
    """The response that ends a traversal: no further node to put."""

    conclusions: tuple[Conclusion, ...] = ()
    raw: Raw = Field(default_factory=dict, repr=False)


Step = Question | Completion


class QARecord(_Model):
    question: str
    answer: str = ""  # the chosen option's label, when one was chosen
    value: str = ""  # typed text, when the node took a value
    raw: Raw = Field(default_factory=dict, repr=False)


class QAResult(_Model):
    records: tuple[QARecord, ...] = ()
    raw: Raw = Field(default_factory=dict, repr=False)
