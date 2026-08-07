"""Graph state.

Shaped the agent's state so the same orchestration
boundary, checkpointer and interrupt/resume contract apply unchanged. The
survey-specific fields sit alongside the shared ones rather than replacing them.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from langgraph.graph.message import add_messages
from typing_extensions import TypedDict

Phase = Literal["opening", "identity", "consent", "survey", "closing", "done"]

# How the call ended. Only "surveyed" carries a full set of answers; every other
# value is the call saying why it does not, which is what makes a survey batch
# readable — an empty answer set with no disposition is indistinguishable from a
# member who hated the program and said nothing.
Disposition = Literal[
    "surveyed",
    "partially_surveyed",
    "uninterested",
    "reschedule_requested",
    # The member asked for a person, or said something that meant one was needed.
    # Both stop the survey where it stands and hand the call over; the second is
    # the one a human must look at today rather than in next month's report.
    "representative_requested",
    "safeguarding_handoff",
    "voicemail_left",
    "policyholder_unavailable",
    "wrong_number",
    "do_not_call",
    "ended_early",
]


class SlotState(TypedDict, total=False):
    attempt_count: int
    confirmed: bool
    last_value: str | None


class SurveyState(TypedDict, total=False):
    # ── shared RCM contract ──────────────────────────────────────────────
    messages: Annotated[list, add_messages]
    metadata_events: list[dict]
    is_interrupt: bool
    next_node: str
    app_run_id: str
    active_agent: str
    last_agent_signal: dict
    workflow_subtype: str
    input_data: dict[str, Any]
    output_data: dict[str, Any]
    phase: Phase

    # ── slot machinery ───────────────────────────────────────────────────
    slot_attempts: dict[str, SlotState]
    awaiting_slot: str
    ambiguous_counts: dict[str, int]
    pending_intents: list[dict]

    # ── call progress ────────────────────────────────────────────────────
    answers: dict[str, str]  # question slot -> recorded answer
    declined: list[str]  # questions put that the member would not answer
    visited_nodes: list[str]  # script node ids, in the order we acted on them
    ask_counts: dict[str, int]  # times each question has been put

    # Who we reached: "" until they say, then confirmed / unavailable /
    # wrong_number. Never inferred from silence — an unanswered greeting is
    # asked again, not assumed to be the policyholder.
    identity: str
    identity_asks: int
    # "" | "granted" | "declined". The document's gate before any question.
    consent: str
    consent_asks: int
    # "" | "yes" | "no", only meaningful once consent is declined.
    reschedule: str
    # Free-text date/time the member gave for the reschedule; "" until collected.
    reschedule_datetime: str
    survey_started: bool

    # ── termination ──────────────────────────────────────────────────────
    disposition: str
    escalation_reason: str

    # ── harness ──────────────────────────────────────────────────────────
    offline: bool  # run with no model: script wording verbatim, no extraction


def initial_state(input_data: dict[str, Any] | None = None, *, app_run_id: str = "") -> SurveyState:
    """A fresh call state. Only explicitly supplied payload values are seeded."""
    return SurveyState(
        messages=[],
        metadata_events=[],
        is_interrupt=False,
        next_node="call_workflow",
        app_run_id=app_run_id,
        active_agent="msat_survey_agent",
        last_agent_signal={},
        workflow_subtype=str((input_data or {}).get("workflow_subtype") or "MEMBER_SATISFACTION_SURVEY"),
        input_data=dict(input_data or {}),
        output_data={},
        phase="opening",
        slot_attempts={},
        awaiting_slot="",
        ambiguous_counts={},
        pending_intents=[],
        answers={},
        declined=[],
        visited_nodes=[],
        ask_counts={},
        identity="",
        identity_asks=0,
        consent="",
        consent_asks=0,
        reschedule="",
        reschedule_datetime="",
        survey_started=False,
        disposition="",
        escalation_reason="",
    )
