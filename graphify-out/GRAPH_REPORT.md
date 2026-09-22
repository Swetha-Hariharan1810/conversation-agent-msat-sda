# Graph Report - .  (2026-08-27)

## Corpus Check
- Corpus is ~42,946 words - fits in a single context window. You may not need a graph.

## Summary
- 753 nodes · 2356 edges · 30 communities detected
- Extraction: 47% EXTRACTED · 53% INFERRED · 0% AMBIGUOUS · INFERRED: 1254 edges (avg confidence: 0.58)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_LLM Client Layer|LLM Client Layer]]
- [[_COMMUNITY_BaseAgent Core|BaseAgent Core]]
- [[_COMMUNITY_Slot Pipeline & Validators|Slot Pipeline & Validators]]
- [[_COMMUNITY_Dialogue Manager & Triage|Dialogue Manager & Triage]]
- [[_COMMUNITY_LangGraph Workflow Boundary|LangGraph Workflow Boundary]]
- [[_COMMUNITY_Prompt Contracts & Structured Output|Prompt Contracts & Structured Output]]
- [[_COMMUNITY_Guard Assessment & Detection|Guard Assessment & Detection]]
- [[_COMMUNITY_Guard Pattern Matching|Guard Pattern Matching]]
- [[_COMMUNITY_Intent & Planner State|Intent & Planner State]]
- [[_COMMUNITY_Turn Timing Tests|Turn Timing Tests]]
- [[_COMMUNITY_Slot Rejection & Retry Tests|Slot Rejection & Retry Tests]]
- [[_COMMUNITY_Payload Reading|Payload Reading]]
- [[_COMMUNITY_JSON Manifest Validation|JSON Manifest Validation]]
- [[_COMMUNITY_Agent Package Root|Agent Package Root]]
- [[_COMMUNITY_Tests Package Init|Tests Package Init]]
- [[_COMMUNITY_Transcript Provider Time|Transcript Provider Time]]
- [[_COMMUNITY_Transcript Member Wait Time|Transcript Member Wait Time]]
- [[_COMMUNITY_Transcript Call Log|Transcript Call Log]]
- [[_COMMUNITY_Transcript Waiting Time|Transcript Waiting Time]]
- [[_COMMUNITY_Transcript Run Directory|Transcript Run Directory]]
- [[_COMMUNITY_Transcript Slowest Turn|Transcript Slowest Turn]]
- [[_COMMUNITY_Transcript Role Breakdown|Transcript Role Breakdown]]
- [[_COMMUNITY_Agents Package Init|Agents Package Init]]
- [[_COMMUNITY_Script Spec Answer Synonyms|Script Spec Answer Synonyms]]
- [[_COMMUNITY_Script Spec Question Order|Script Spec Question Order]]
- [[_COMMUNITY_Script Spec Slot Order|Script Spec Slot Order]]
- [[_COMMUNITY_Script Spec Gating Facts|Script Spec Gating Facts]]
- [[_COMMUNITY_Script Package Init|Script Package Init]]
- [[_COMMUNITY_Core Package Init|Core Package Init]]
- [[_COMMUNITY_Slots Package Init|Slots Package Init]]

## God Nodes (most connected - your core abstractions)
1. `MsatSurveyAgent` - 121 edges
2. `TurnDecision` - 114 edges
3. `EventType` - 66 edges
4. `Chat` - 64 edges
5. `GuardAssessment` - 60 edges
6. `SecondaryIntentKind` - 59 edges
7. `SurveySpec` - 57 edges
8. `SecondaryIntent` - 52 edges
9. `SurveyState` - 50 edges
10. `IntentKind` - 47 edges

## Surprising Connections (you probably didn't know these)
- `What the same live scenarios do when the provider is gone.  This is the one part` --uses--> `MsatSurveyAgent`  [INFERRED]
  tests/test_guard_fallback.py → msat_flow/agents/survey_agent.py
- `Every call fails, the way a provider outage or an exhausted retry does.      ``r` --uses--> `MsatSurveyAgent`  [INFERRED]
  tests/test_guard_fallback.py → msat_flow/agents/survey_agent.py
- `A failed guard degrades. Reading a turn is allowed to end a call; this is not.` --uses--> `MsatSurveyAgent`  [INFERRED]
  tests/test_guard_fallback.py → msat_flow/agents/survey_agent.py
- `The plain disclosures stay catchable with no model at all.      These are the tu` --uses--> `MsatSurveyAgent`  [INFERRED]
  tests/test_guard_fallback.py → msat_flow/agents/survey_agent.py
- `Report which live scenarios the patterns alone cannot decide.      Not a pass/fa` --uses--> `MsatSurveyAgent`  [INFERRED]
  tests/test_guard_fallback.py → msat_flow/agents/survey_agent.py

## Hyperedges (group relationships)
- **Speak Line Prompt Composition** — speak_line_user, speak_line_context, speak_line_values, speak_line_options, speak_line_reference, speak_line_progress, speak_line_attempt, speak_line_preamble, speak_line_acknowledge [EXTRACTED 0.85]
- **Guard Detection Pipeline** — detect_guards_system, detect_guards_user, readme_live_tests, msat_flow_core_guards_py [EXTRACTED 0.80]
- **Turn Extraction Pipeline** — extract_turn_system, extract_turn_user, msat_flow_llm_extractor_py [INFERRED 0.70]

## Communities

### Community 0 - "LLM Client Layer"
Cohesion: 0.03
Nodes (98): _env(), LLMClient, An HTTP client whose idle connections expire rather than rot., Fire a 1-token dummy call to pre-establish the TCP+TLS connection., Structured + free-text calls against an OpenAI or Azure OpenAI chat model., client(), _publish_recorder(), pytest_report_header() (+90 more)

### Community 1 - "BaseAgent Core"
Cohesion: 0.05
Nodes (84): BaseAgent, BaseAgent — the shared infrastructure every survey agent inherits.  Composed exa, Abstract base for survey agents., Rebuild the agent's working memory from persisted graph state., Record which script node this turn came from., The agent's working memory, as state updates., ConversationGuardsMixin, DialogueManagerMixin (+76 more)

### Community 2 - "Slot Pipeline & Validators"
Cohesion: 0.04
Nodes (80): The scenario table ``name``, as a list of dicts., scenarios(), _flatten(), normalize(), normalize_choice(), normalize_feedback_text(), normalize_person_name(), normalize_yes_no() (+72 more)

### Community 3 - "Dialogue Manager & Triage"
Cohesion: 0.09
Nodes (95): BaseAgent, BaseModel, _captured_as(), classify(), _classify_by_wording(), DialogueManagerMixin, intent_text(), Capture everything the member raised in a turn, not just the answer.  One extrac (+87 more)

### Community 4 - "LangGraph Workflow Boundary"
Cohesion: 0.06
Nodes (37): ABC, from_state(), call_workflow(), human_node(), LangGraph boundary  One workflow node runs the agent; one human node parks on ``, Run one agent turn.      ``offline`` state runs the agent with no model at all:, Park until the member's next turn arrives, then resume the workflow., Call Outcome Contract (+29 more)

### Community 5 - "Prompt Contracts & Structured Output"
Cohesion: 0.06
Nodes (45): Thin structured-output client.  Kept deliberately small: the agent depends on ``, What the agent needs of a client — a real one or a scripted stub.      ``role``, SupportsStructured, Detect Guards System Prompt, Detect Guards User Prompt, Extract Turn System Prompt, Extract Turn User Prompt, build_messages() (+37 more)

### Community 6 - "Guard Assessment & Detection"
Cohesion: 0.11
Nodes (41): run(), GuardAssessment, Whether one member turn is something the survey cannot carry on through.      Fi, initial_state(), A fresh call state. Only explicitly supplied payload values are seeded., _chat(), The guard call and the extraction call go out together.  Both are put the same t, `generate` reads the planner's decision, so it cannot join the other two. (+33 more)

### Community 7 - "Guard Pattern Matching"
Cohesion: 0.08
Nodes (27): detect(), What the model makes of this turn.      Raises whatever the provider raises. The, match_patterns(), The guard this turn's *wording* trips, or "" — the fallback detector., describe(), failure(), Read the scenario tables.  Scenarios are JSON, not Python, for the same reason t, The scenario's own account of why it exists, for the failure message. (+19 more)

### Community 8 - "Intent & Planner State"
Cohesion: 0.18
Nodes (21): add_intent(), Append unless an identical open intent is already queued., agent(), _answered(), _ask(), _plan(), test_a_correction_on_the_ledger_does_not_by_itself_block_a_plain_ask(), test_a_question_never_put_before_answering_a_plain_answer() (+13 more)

### Community 9 - "Turn Timing Tests"
Cohesion: 0.3
Nodes (20): _closed_after(), _everything_at_once(), _ledger(), _raised(), _resumed(), _state(), _still_open(), test_a_call_of_nothing_but_chat_reports_nothing() (+12 more)

### Community 10 - "Slot Rejection & Retry Tests"
Cohesion: 0.34
Nodes (14): Every prompt sent for ``role``, flattened to one string per call., _asks_back(), _state(), test_a_correction_alongside_a_question_back_still_gets_the_context(), test_a_repeat_request_does_not_spend_an_attempt(), test_an_answer_the_slot_rejected_keeps_its_own_reason(), test_an_answer_with_nothing_in_it_still_spends_one(), test_an_unclear_answer_still_spends_one() (+6 more)

### Community 11 - "Payload Reading"
Cohesion: 0.29
Nodes (7): missing_required(), Read work-item values out of the inbound payload.  Two things come from the work, Read one dotted path. Missing, null and empty all read as absent., The payload's value for ``slot``, or "" if the work item does not carry it., Required sections and fields the work item does not carry, dotted-path.      Mir, _read(), resolve()

### Community 12 - "JSON Manifest Validation"
Cohesion: 0.33
Nodes (3): Every JSON file this project ships must parse.  This exists because ``langgraph., The two lines in langgraph.json anything depends on.      ``graphs`` is what ``l, test_the_graph_manifest_still_points_at_the_graph()

### Community 13 - "Agent Package Root"
Cohesion: 1.0
Nodes (1): Outbound member-satisfaction survey agent.

### Community 14 - "Tests Package Init"
Cohesion: 1.0
Nodes (0):

### Community 15 - "Transcript Provider Time"
Cohesion: 1.0
Nodes (1): What the provider spent on this turn, overlap counted twice.

### Community 16 - "Transcript Member Wait Time"
Cohesion: 1.0
Nodes (1): What the member waited for it, overlap counted once.          Below ``calls_s``

### Community 17 - "Transcript Call Log"
Cohesion: 1.0
Nodes (1): Every provider call this conversation made, in order.

### Community 18 - "Transcript Waiting Time"
Cohesion: 1.0
Nodes (1): Time this test spent waiting on the provider, overlap counted once.          Sum

### Community 19 - "Transcript Run Directory"
Cohesion: 1.0
Nodes (1): The run's directory, created on first write rather than at startup.          A s

### Community 20 - "Transcript Slowest Turn"
Cohesion: 1.0
Nodes (1): Slowest turn first — the one a member would have noticed.

### Community 21 - "Transcript Role Breakdown"
Cohesion: 1.0
Nodes (1): Where this test's time went, by the role each provider call played.          The

### Community 22 - "Agents Package Init"
Cohesion: 1.0
Nodes (0):

### Community 23 - "Script Spec Answer Synonyms"
Cohesion: 1.0
Nodes (1): Everything a member could say that means this option.

### Community 24 - "Script Spec Question Order"
Cohesion: 1.0
Nodes (1): The survey's questions, in the order the document prints them.

### Community 25 - "Script Spec Slot Order"
Cohesion: 1.0
Nodes (1): Slots the survey asks for, in question order.

### Community 26 - "Script Spec Gating Facts"
Cohesion: 1.0
Nodes (1): Work-item facts that decide which questions this member is asked.          Repor

### Community 27 - "Script Package Init"
Cohesion: 1.0
Nodes (0):

### Community 28 - "Core Package Init"
Cohesion: 1.0
Nodes (0):

### Community 29 - "Slots Package Init"
Cohesion: 1.0
Nodes (0):

## Knowledge Gaps
- **87 isolated node(s):** `Every JSON file this project ships must parse.  This exists because ``langgraph.`, `The two lines in langgraph.json anything depends on.      ``graphs`` is what ``l`, `Read the scenario tables.  Scenarios are JSON, not Python, for the same reason t`, `The scenario table ``name``, as a list of dicts.`, `The scenario's own account of why it exists, for the failure message.` (+82 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Agent Package Root`** (2 nodes): `Outbound member-satisfaction survey agent.`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Tests Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Transcript Provider Time`** (1 nodes): `What the provider spent on this turn, overlap counted twice.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Transcript Member Wait Time`** (1 nodes): `What the member waited for it, overlap counted once.          Below ``calls_s```
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Transcript Call Log`** (1 nodes): `Every provider call this conversation made, in order.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Transcript Waiting Time`** (1 nodes): `Time this test spent waiting on the provider, overlap counted once.          Sum`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Transcript Run Directory`** (1 nodes): `The run's directory, created on first write rather than at startup.          A s`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Transcript Slowest Turn`** (1 nodes): `Slowest turn first — the one a member would have noticed.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Transcript Role Breakdown`** (1 nodes): `Where this test's time went, by the role each provider call played.          The`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Agents Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Script Spec Answer Synonyms`** (1 nodes): `Everything a member could say that means this option.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Script Spec Question Order`** (1 nodes): `The survey's questions, in the order the document prints them.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Script Spec Slot Order`** (1 nodes): `Slots the survey asks for, in question order.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Script Spec Gating Facts`** (1 nodes): `Work-item facts that decide which questions this member is asked.          Repor`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Script Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Core Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Slots Package Init`** (1 nodes): `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `MsatSurveyAgent` connect `Dialogue Manager & Triage` to `LLM Client Layer`, `BaseAgent Core`, `Slot Pipeline & Validators`, `LangGraph Workflow Boundary`, `Prompt Contracts & Structured Output`, `Guard Assessment & Detection`, `Guard Pattern Matching`, `Intent & Planner State`, `Turn Timing Tests`, `Slot Rejection & Retry Tests`?**
  _High betweenness centrality (0.313) - this node is a cross-community bridge._
- **Why does `TurnDecision` connect `Dialogue Manager & Triage` to `LLM Client Layer`, `BaseAgent Core`, `LangGraph Workflow Boundary`, `Prompt Contracts & Structured Output`, `Guard Assessment & Detection`, `Intent & Planner State`, `Turn Timing Tests`, `Slot Rejection & Retry Tests`?**
  _High betweenness centrality (0.115) - this node is a cross-community bridge._
- **Why does `SurveySpec` connect `BaseAgent Core` to `Slot Pipeline & Validators`, `Dialogue Manager & Triage`, `LangGraph Workflow Boundary`, `Prompt Contracts & Structured Output`, `Payload Reading`?**
  _High betweenness centrality (0.114) - this node is a cross-community bridge._
- **Are the 101 inferred relationships involving `MsatSurveyAgent` (e.g. with `What closes each thing the member raised, and what is left open.  The ledger is` and `One turn through the real agent, with the extractor scripted.`) actually correct?**
  _`MsatSurveyAgent` has 101 INFERRED edges - model-reasoned connections that need verification._
- **Are the 111 inferred relationships involving `TurnDecision` (e.g. with `Spoken` and `Chain`) actually correct?**
  _`TurnDecision` has 111 INFERRED edges - model-reasoned connections that need verification._
- **Are the 63 inferred relationships involving `EventType` (e.g. with `What closes each thing the member raised, and what is left open.  The ledger is` and `One turn through the real agent, with the extractor scripted.`) actually correct?**
  _`EventType` has 63 INFERRED edges - model-reasoned connections that need verification._
- **Are the 56 inferred relationships involving `Chat` (e.g. with `LLMClient` and `GuardAssessment`) actually correct?**
  _`Chat` has 56 INFERRED edges - model-reasoned connections that need verification._
