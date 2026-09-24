"""How to treat an Expert24 node before anything is said to the member.

Most nodes are questions and are put to the member as they come. A traversal can
also contain nodes that are not for the member — an internal check on a risk
level, say — and a survey's ``node_rules`` say what to do with those. A node no
rule matches is asked; one with nothing to answer is spoken and passed.
"""

from __future__ import annotations

from ..e24.models import Question, QuestionKind
from .definition import NodeAction, NodeRule, SurveyDefinition
from .work_item import CallContext


class NodeRuleError(ValueError):
    """A rule matched but could not produce an answer the node accepts."""


def rule_for(survey: SurveyDefinition, question: Question) -> NodeRule | None:
    for rule in survey.node_rules:
        match = rule.match
        if match.node_id is not None and match.node_id != question.node_id:
            continue
        if match.text_contains is not None and (
            match.text_contains.casefold() not in question.text.casefold()
        ):
            continue
        return rule
    return None


def action_for(survey: SurveyDefinition, question: Question) -> NodeAction:
    rule = rule_for(survey, question)
    if rule is not None:
        return rule.action
    return NodeAction.SPEAK if question.kind is QuestionKind.NONE else NodeAction.ASK


def auto_answer(rule: NodeRule, question: Question, context: CallContext) -> dict[str, str]:
    """The ``/Next`` answers for an auto-answered node, keyed by option index."""
    assert rule.answer is not None
    if rule.answer.option is not None:
        label = rule.answer.option
    else:
        assert rule.answer.source is not None
        value = context.lookup(rule.answer.source)
        if value is None:
            raise NodeRuleError(
                f"node {question.node_id}: {rule.answer.source} is absent from the work item"
            )
        label = rule.answer.map.get(str(value), str(value))

    for option in question.options:
        if option.label.casefold() == label.casefold():
            return {option.index: ""}
    offered = ", ".join(o.label for o in question.options) or "none"
    raise NodeRuleError(
        f"node {question.node_id}: no option labelled {label!r} (offered: {offered})"
    )
