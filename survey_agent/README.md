# survey_agent

The generic replacement for `msat_flow`. One engine runs any Expert24 survey:
the conversation around the survey (voicemail, identity, consent, reschedule,
guards) lives here; the questionnaire — wording, options, branching — comes
from Expert24 one node at a time.

`msat_flow/` stays in the repository as reference until this package replaces it.

## Build order

| Step | What | Status |
|---|---|---|
| 1 | Expert24 integration: settings, async client, models, adapters, errors | **done** |
| 2 | Survey registry and per-survey config: algorithm id, input schema, prepop mapping, node rules | **done** |
| 3 | Extraction slots built from each E24 node; guard and extraction ported | |
| 4 | Engine: conversation shell, E24 question loop, LangGraph boundary | |
| 5 | Outcome from QA, observability, CI, container | |

## Expert24 (`e24/`)

```
start     POST /Member                                  -> TraversalHandles
first     POST /First/{tid}/{mid}/{algo}/0?Language=... -> Question | Completion
next      POST /Next/{tid}/{mid}/{algo}/{node}          -> Question | Completion
previous  GET  /Previous/{tid}                          -> Question | Completion
qa        GET  /QA/{tid}                                -> QAResult
```

- **Models** (`models.py`) are the only thing the engine sees. Each keeps the raw
  payload, so a field Expert24 adds is never lost.
- **Adapters** (`adapter.py`): `RequestBuilder` shapes the bodies we send,
  `ResponseAdapter` reads what comes back. The defaults match the direct
  TraversalService; a survey whose payload or response differs subclasses one
  and overrides a method.
- **Retries**: only when a request cannot take effect twice. Connection refused
  and proxy 502/503 are retried for every call. A timeout or 504 after sending
  is retried only for `qa`; for the others it raises `E24UncertainOutcome`,
  because resending `Next` could answer a question twice.
- **Logging**: operation, status and timing only — never bodies or member ids.

Reference material for the API is in `docs/e24/`.

## Surveys (`surveys/`, `catalog/`)

A survey is a folder under `catalog/` with one `survey.yaml`; the registry finds
it by `workflow_subtype`. Nothing is registered in code, and the whole catalogue
is validated at startup, so a bad file fails the deploy rather than a call.

A call's only input is the work item:

```json
{
  "workflow_subtype": "MEMBER_SATISFACTION_SURVEY",
  "member_id": "ABC_TMJarrett",
  "prepop": {
    "DOB": "2010-01-06",
    "FallPrevRiskLevel": "No",
    "Gender": "Male",
    "FirstName": "Jarrett",
    "source_application": "AgentPortal"
  }
}
```

`member_id` becomes Expert24's `@UserID`. `prepop` is checked against the
survey's declared fields (type, required, choices, default) and sent as
`Prepop` exactly as given — values are checked, never rewritten. Every problem
is reported at once. Undeclared fields are forwarded (`extra: allow`) or refused
(`extra: forbid`), per survey.

`speak_values` names the work-item values the conversation may say
(`first_name: prepop.FirstName`).

`node_rules` cover the nodes that are not for the member. With no rule, a node
with options is asked and a node with nothing to answer is spoken and passed.
A rule matches on `node_id` and/or `text_contains` and can `speak`, pass
`silent`ly, or `auto_answer` from the work item:

```yaml
node_rules:
  - match: {node_id: "889"}
    action: auto_answer
    answer: {source: prepop.FallPrevRiskLevel, map: {"3": "Yes"}}
```

A survey file holds no question wording; that is Expert24's.

## Settings

| Variable | Default | |
|---|---|---|
| `E24_BASE_URL` | *(required)* | Host that reaches Expert24 |
| `E24_API_ROOT` | `/webbuilder/TraversalService` | |
| `E24_LANGUAGE` | `MEMBER` | `Language` on `/First` |
| `E24_CONNECT_TIMEOUT` | `3.0` | seconds |
| `E24_READ_TIMEOUT` | `8.0` | seconds — the member is waiting on the line |
| `E24_MAX_RETRIES` | `2` | for retry-safe failures only |
| `E24_BACKOFF_BASE` | `0.25` | seconds, exponential with jitter |
| `E24_VERIFY_TLS` | `true` | |

Authentication is not configured yet: the reference script sends none. The
client accepts an `httpx.Auth`, so adding it is a settings change, not a
client change.

## Checks

```bash
uv run pytest tests/e24 tests/surveys
uv run ruff check survey_agent tests/e24 tests/surveys
uv run mypy
```

`tests/e24/fixtures/msat_10657/walk.json` is reconstructed from the UAT run in
`docs/e24/SCRIPT_EXPLAINED_README.md`. Replace it with a real capture
(`e24_direct_client.py run --save`) when one is available.
