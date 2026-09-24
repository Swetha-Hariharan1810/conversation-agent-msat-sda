"""What makes one survey different from another.

A survey is a folder under ``catalog/`` holding one ``survey.yaml``. Everything
the engine needs to run it is here: which Expert24 algorithm to traverse, what
the work item must carry, what goes into ``Prepop``, which values the
conversation may speak, and how to treat the few nodes that are not meant for
the member. No question wording lives here — that is Expert24's.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Config(BaseModel):
    # A typo in a survey file must fail at load, not be silently ignored.
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldType(StrEnum):
    STRING = "string"
    DATE = "date"  # ISO 8601, YYYY-MM-DD
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"


class PrepopField(_Config):
    type: FieldType = FieldType.STRING
    required: bool = True
    choices: tuple[str, ...] | None = None
    default: Any = None
    description: str = ""

    @model_validator(mode="after")
    def _default_is_optional(self) -> PrepopField:
        if self.default is not None and self.required:
            raise ValueError("a field with a default must not also be required")
        return self


class ExtraFields(StrEnum):
    ALLOW = "allow"  # forwarded to Expert24 unchanged
    FORBID = "forbid"  # the work item is refused


class PrepopSpec(_Config):
    fields: dict[str, PrepopField] = Field(default_factory=dict)
    extra: ExtraFields = ExtraFields.ALLOW


class E24Target(_Config):
    algorithm_id: str
    language: str | None = None  # falls back to E24_LANGUAGE


class NodeAction(StrEnum):
    ASK = "ask"  # put it to the member (the default for every node)
    SPEAK = "speak"  # read it out, submit nothing, continue
    SILENT = "silent"  # do not read it, submit nothing, continue
    AUTO_ANSWER = "auto_answer"  # do not read it, answer it from the work item


class NodeMatch(_Config):
    """Match on the node id, the text, or both (all given must hold)."""

    node_id: str | None = None
    text_contains: str | None = None

    @model_validator(mode="after")
    def _something_to_match(self) -> NodeMatch:
        if self.node_id is None and self.text_contains is None:
            raise ValueError("a node match needs node_id or text_contains")
        return self


class AutoAnswer(_Config):
    """Which option to pick, as the option's label.

    Either a fixed ``option``, or the value at ``source`` (a work-item path such
    as ``prepop.FallPrevRiskLevel``) translated through ``map``. A value with no
    entry in ``map`` is used as the label itself.
    """

    option: str | None = None
    source: str | None = None
    map: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_way_to_answer(self) -> AutoAnswer:
        if (self.option is None) == (self.source is None):
            raise ValueError("auto answer needs exactly one of option or source")
        return self


class NodeRule(_Config):
    match: NodeMatch
    action: NodeAction
    answer: AutoAnswer | None = None
    reason: str = ""

    @model_validator(mode="after")
    def _answer_only_for_auto(self) -> NodeRule:
        if (self.action is NodeAction.AUTO_ANSWER) != (self.answer is not None):
            raise ValueError("answer is required for auto_answer and only for auto_answer")
        return self


class SurveyDefinition(_Config):
    workflow_subtype: str
    name: str
    e24: E24Target
    prepop: PrepopSpec = Field(default_factory=PrepopSpec)
    # Values the conversation may speak, each a work-item path.
    speak_values: dict[str, str] = Field(default_factory=dict)
    node_rules: tuple[NodeRule, ...] = ()
    # Which set of conversation lines (intro, consent, voicemail...) to use.
    conversation: str = "default"
