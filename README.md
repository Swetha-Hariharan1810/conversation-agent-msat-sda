# Member Satisfaction Survey (MSAT) Agent

An outbound voice agent that calls Smart Step program participants, administers
the Allianz Member Satisfaction Survey, and returns a structured call outcome.

It follows the architecture — a `BaseAgent` composed of guards, slot management,
signals and dialogue management, behind a LangGraph
`interrupt()`/resume boundary — with two differences that shape everything:

- **The person on the line is a member, not a professional.** They did not ask
  for this call, they owe us nothing, and every question is one they may decline.
- **The questionnaire has conditions.** Two questions depend on an answer given
  earlier in the call; one depends on a fact the work item brings and the call
  can never learn. Getting a condition wrong does not fail loudly — it produces
  a clean-looking result about a question this member was never asked.

---

## The call

| | |
|---|---|
| **At any point** | A member who may be at risk, or who asks for a person, stops the survey and gets one |
| **Introduction** | Introduce Ida, ask for the policyholder by name, then ask for a couple of minutes |
| **If not now** | Offer to reschedule → hand to a human to rebook, or thank them and close |
| **Survey** | Six questions; 1a *or* 1b depending on Q1; Q5 only for high-risk policyholders |
| **Closing** | Thank them and say goodbye |

The six questions, as the document prints them:

| | Question | Answers |
|---|---|---|
| 1 | Reviewed any program resources (action plans, articles, videos, websites)? | yes / no |
| 1a | *(if yes)* How helpful were they in making at least one lifestyle change? | extremely / somewhat / not very / definitely not helpful |
| 1b | *(if no)* Why not? | no time / not interested / portal not working / other |
| 2 | What changes or additions would improve the program? | free text; "no" or "none" is an answer |
| 3 | What did you like most about the program? | free text; "no" or "none" is an answer |
| 4 | Would you recommend the program to people you know? | yes / no |
| 5 | Were program staff helpful and knowledgeable? | yes / no — **high-risk only** |
| 6 | Overall experience? | extremely / somewhat / not very / definitely not helpful |

---

### Serving the graph

```bash
uv run langgraph dev
```

`langgraph.json` points at `msat_flow/app_graph.py:graph`, compiled without a
local checkpointer so persistence is platform-managed. In-process callers use
`build_graph(with_checkpointer=True)`.

---

## Input and output

Input follows this payload shape, validated against `data/input_schema.json`.
The work item brings exactly two facts to the call:

```json
{
  "workflow_subtype": "MEMBER_SATISFACTION_SURVEY",
  "policyholder": {
    "first_name": "Margaret",
    "last_name": "Ellison",
    "risk_tier": "high"
  }
}
```

`risk_tier` decides whether question 5 is asked. It is never inferred and nothing
said on the call can change it; a work item that does not carry one is reported
by the CLI before the call starts, and if a call runs anyway the question is
skipped rather than guessed.

Output is `{"call_outcome": ...}` per `data/outcome_schema.json`:

```json
{
  "call_outcome": {
    "status": "complete",
    "disposition": "surveyed",
    "workflow_subtype": "MEMBER_SATISFACTION_SURVEY",
    "gating_facts": { "risk_tier": "rising" },
    "answers": {
      "reviewed_resources": "yes",
      "resource_helpfulness": "somewhat_helpful",
      "improvement_feedback": "More phone check-ins would help.",
      "liked_most": "none",
      "would_recommend": "yes",
      "overall_experience": "extremely_helpful"
    },
    "declined_questions": [],
    "skipped_questions": [
      { "slot": "staff_helpful", "node": "sv.05", "reason": "payload risk_tier is not high" },
      { "slot": "no_review_reason", "node": "sv.01b", "reason": "answer reviewed_resources is not no" }
    ],
    "missing_questions": [],
    "visited_nodes": ["in.01", "in.02", "sv.00", "sv.01"],
    "open_intents": []
  }
}
```

Three different kinds of "no answer", kept apart on purpose:

| | |
|---|---|
| `declined_questions` | put, and the member would rather not say |
| `skipped_questions` | this member's script never included it, with the condition that ruled it out |
| `missing_questions` | applicable, never answered — the call ended first |

`disposition` says how the call ended: `surveyed`, `partially_surveyed`,
`uninterested`, `reschedule_requested`, `voicemail_left`,
`policyholder_unavailable`, `wrong_number`, `do_not_call`, `ended_early`. Only
the last is reported as `status: incomplete` — a member who declined to take part
is a correct outcome, and burying refusals in with the technical faults would
make both harder to see.

---
