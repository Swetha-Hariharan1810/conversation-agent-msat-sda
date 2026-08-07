"""LangGraph boundary

One workflow node runs the agent; one human node parks on ``interrupt()`` until
the member's next turn arrives. All conversation state lives in ``SurveyState``,
so a checkpointer can resume a call mid-flight.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from .agents.survey_agent import MsatSurveyAgent, _last_message
from .llm.client import LLMClient
from .state import SurveyState


async def call_workflow(state: SurveyState) -> dict[str, Any]:
    """Run one agent turn.

    ``offline`` state runs the agent with no model at all: the script wording is
    spoken verbatim and nothing is extracted. It exists so the graph can be
    exercised end to end without a provider.
    """
    agent = MsatSurveyAgent.from_state(state)
    agent.client = None if state.get("offline") else LLMClient()
    return await agent.execute(state)


def conditional_routing(state: SurveyState) -> str:
    if state.get("is_interrupt"):
        return "human_node"
    if state.get("next_node") == "END":
        return END
    return state.get("next_node") or "call_workflow"


def human_node(state: SurveyState):
    """Park until the member's next turn arrives, then resume the workflow."""
    prompt = _last_message(state.get("messages", []), "assistant")
    reply = interrupt(prompt)
    return Command(
        goto="call_workflow",
        update={"is_interrupt": False, "messages": [{"role": "user", "content": str(reply)}]},
    )


def build_graph(*, with_checkpointer: bool = True):
    builder = StateGraph(SurveyState)
    builder.add_node("call_workflow", call_workflow)
    builder.add_node("human_node", human_node)
    builder.add_conditional_edges("call_workflow", conditional_routing)
    builder.set_entry_point("call_workflow")
    if with_checkpointer:
        from langgraph.checkpoint.memory import MemorySaver

        return builder.compile(checkpointer=MemorySaver())
    return builder.compile()


# Module-level graph for LangGraph CLI / Platform: persistence is managed there.
graph = build_graph(with_checkpointer=False)

__all__ = ["build_graph", "call_workflow", "conditional_routing", "graph", "human_node"]
