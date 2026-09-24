"""Survey catalogue, work-item preparation and node rules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from survey_agent.e24 import DefaultResponseAdapter, Question
from survey_agent.surveys import (
    NodeAction,
    NodeRuleError,
    SurveyConfigError,
    SurveyDefinition,
    SurveyRegistry,
    UnknownSurvey,
    WorkItemError,
    action_for,
    auto_answer,
    prepare,
    rule_for,
)

MSAT = "MEMBER_SATISFACTION_SURVEY"
PREPOP = {
    "DOB": "2010-01-06",
    "FallPrevRiskLevel": "No",
    "Gender": "Male",
    "FirstName": "Jarrett",
    "source_application": "AgentPortal",
}
WALK = json.loads((Path(__file__).parent.parent / "e24/fixtures/msat_10657/walk.json").read_text())


def node(node_id: int) -> Question:
    for step in [{"response": WALK["first"]}, *WALK["next"]]:
        if step["response"].get("NodeID") == node_id:
            q = DefaultResponseAdapter().step(step["response"])
            assert isinstance(q, Question)
            return q
    raise KeyError(node_id)


@pytest.fixture(scope="module")
def registry() -> SurveyRegistry:
    return SurveyRegistry.from_directory()


def survey(**overrides: Any) -> SurveyDefinition:
    base: dict[str, Any] = {
        "workflow_subtype": "TEST",
        "name": "Test",
        "e24": {"algorithm_id": "1"},
    }
    return SurveyDefinition.model_validate({**base, **overrides})


# -- the catalogue -----------------------------------------------------------


def test_catalogue_loads_msat(registry: SurveyRegistry) -> None:
    msat = registry.get(MSAT)
    assert msat.e24.algorithm_id == "10657"
    assert set(msat.prepop.fields) == set(PREPOP)


def test_unknown_subtype_names_the_known_ones(registry: SurveyRegistry) -> None:
    with pytest.raises(UnknownSurvey, match=MSAT):
        registry.get("NOPE")


def test_a_new_survey_is_just_a_folder(tmp_path: Path) -> None:
    for name, subtype in [("a", "A"), ("b", "B")]:
        (tmp_path / name).mkdir()
        (tmp_path / name / "survey.yaml").write_text(
            f"workflow_subtype: {subtype}\nname: {name}\ne24: {{algorithm_id: '1'}}\n"
        )
    assert {s.workflow_subtype for s in SurveyRegistry.from_directory(tmp_path)} == {"A", "B"}


def test_duplicate_subtype_is_refused() -> None:
    with pytest.raises(SurveyConfigError, match="defined twice"):
        SurveyRegistry([survey(), survey()])


def test_a_typo_in_a_survey_file_fails_at_load(tmp_path: Path) -> None:
    (tmp_path / "x").mkdir()
    (tmp_path / "x" / "survey.yaml").write_text(
        "workflow_subtype: X\nname: x\ne24: {algorithm_id: '1'}\nnode_rule: []\n"
    )
    with pytest.raises(SurveyConfigError, match="survey.yaml"):
        SurveyRegistry.from_directory(tmp_path)


@pytest.mark.parametrize(
    "rule",
    [
        {"match": {}, "action": "ask"},
        {"match": {"node_id": "1"}, "action": "auto_answer"},
        {"match": {"node_id": "1"}, "action": "ask", "answer": {"option": "Yes"}},
        {"match": {"node_id": "1"}, "action": "auto_answer", "answer": {}},
    ],
)
def test_malformed_node_rules_are_refused(rule: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        survey(node_rules=[rule])


# -- work items --------------------------------------------------------------


def test_msat_work_item_is_prepared_unchanged(registry: SurveyRegistry) -> None:
    ctx = prepare(registry.get(MSAT), {"member_id": "ABC_TMJarrett", "prepop": PREPOP})
    assert ctx.member_id == "ABC_TMJarrett"
    assert ctx.prepop == PREPOP
    assert ctx.speak_values == {"first_name": "Jarrett"}


def test_default_fills_a_missing_optional_field(registry: SurveyRegistry) -> None:
    prepop = {k: v for k, v in PREPOP.items() if k != "source_application"}
    ctx = prepare(registry.get(MSAT), {"member_id": "M", "prepop": prepop})
    assert ctx.prepop["source_application"] == "AgentPortal"


def test_every_problem_is_reported_at_once(registry: SurveyRegistry) -> None:
    prepop = {**PREPOP, "DOB": "06/01/2010", "Gender": 1}
    del prepop["FirstName"]
    with pytest.raises(WorkItemError) as info:
        prepare(registry.get(MSAT), {"prepop": prepop})
    assert info.value.problems == [
        "member_id is required",
        "prepop.FirstName is required",
        "prepop.DOB must be a date as YYYY-MM-DD; got '06/01/2010'",
        "prepop.Gender must be a string",
    ]


def test_impossible_date_is_refused(registry: SurveyRegistry) -> None:
    with pytest.raises(WorkItemError, match="DOB"):
        prepare(registry.get(MSAT), {"member_id": "M", "prepop": {**PREPOP, "DOB": "2010-02-30"}})


def test_undeclared_fields_follow_the_survey_policy() -> None:
    work_item = {"member_id": "M", "prepop": {"Known": "a", "Other": "b"}}
    allow = survey(prepop={"fields": {"Known": {}}})
    assert prepare(allow, work_item).prepop == {"Known": "a", "Other": "b"}

    forbid = survey(prepop={"fields": {"Known": {}}, "extra": "forbid"})
    with pytest.raises(WorkItemError, match="undeclared fields: Other"):
        prepare(forbid, work_item)


def test_choices_are_enforced() -> None:
    s = survey(prepop={"fields": {"Level": {"choices": ["1", "2", "3"]}}})
    with pytest.raises(WorkItemError, match="one of 1, 2, 3"):
        prepare(s, {"member_id": "M", "prepop": {"Level": "4"}})


# -- node rules --------------------------------------------------------------


def test_without_rules_questions_are_asked_and_statements_spoken(
    registry: SurveyRegistry,
) -> None:
    msat = registry.get(MSAT)
    assert action_for(msat, node(908)) is NodeAction.ASK
    assert action_for(msat, node(903)) is NodeAction.ASK
    assert action_for(msat, node(487)) is NodeAction.SPEAK
    assert action_for(msat, node(876)) is NodeAction.SPEAK


def test_rule_matches_on_id_or_text() -> None:
    s = survey(
        node_rules=[
            {"match": {"text_contains": "risk level"}, "action": "silent"},
            {"match": {"node_id": "908"}, "action": "speak"},
        ]
    )
    assert action_for(s, node(889)) is NodeAction.SILENT
    assert action_for(s, node(908)) is NodeAction.SPEAK
    assert rule_for(s, node(966)) is None


def test_auto_answer_from_the_work_item_through_a_map() -> None:
    s = survey(
        prepop={"fields": {"Risk": {}}},
        node_rules=[
            {
                "match": {"node_id": "889"},
                "action": "auto_answer",
                "answer": {"source": "prepop.Risk", "map": {"3": "Yes"}},
            }
        ],
    )
    rule = rule_for(s, node(889))
    assert rule is not None
    high = prepare(s, {"member_id": "M", "prepop": {"Risk": "3"}})
    assert auto_answer(rule, node(889), high) == {"1": ""}
    # a value with no map entry is used as the label itself
    low = prepare(s, {"member_id": "M", "prepop": {"Risk": "no"}})
    assert auto_answer(rule, node(889), low) == {"2": ""}


def test_auto_answer_with_no_matching_option_is_an_error() -> None:
    s = survey(
        node_rules=[
            {"match": {"node_id": "889"}, "action": "auto_answer", "answer": {"option": "Maybe"}}
        ]
    )
    rule = rule_for(s, node(889))
    assert rule is not None
    ctx = prepare(s, {"member_id": "M", "prepop": {}})
    with pytest.raises(NodeRuleError, match="offered: Yes, No"):
        auto_answer(rule, node(889), ctx)
