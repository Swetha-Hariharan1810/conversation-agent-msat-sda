# Live tests

Everything here sends real requests to the configured provider. They are the only
tests that can tell you whether the prompts actually work — a stub can prove the
plumbing is right and nothing else.

```bash
# opt in, with credentials in the environment exactly as a call would have them
MSAT_LIVE_TESTS=1 uv run pytest tests/live -v

# whole calls only — nine complete surveys, the expensive and most useful file
MSAT_LIVE_TESTS=1 uv run pytest tests/live/test_full_calls.py -v

# just the guards, four times each, to see whether the answers are stable
MSAT_LIVE_TESTS=1 MSAT_LIVE_REPEAT=4 uv run pytest tests/live/test_guard_detection.py -v

# everything except the live tests (the default for anyone who has not opted in)
uv run pytest -m "not live"
```

Without `MSAT_LIVE_TESTS=1` the whole directory skips and says so. With the flag
but no credentials it skips and names the missing variable, rather than failing
as though the prompt were wrong.

## Credentials

They come from `.env` at the repo root — the same file `langgraph.json` points
at — which the tests load themselves. That matters: under `langgraph dev` the
server reads `.env` for you, so nothing else in this project ever had to, and a
test gate built on `os.getenv` alone would report "no credentials" to somebody
looking straight at theirs. An exported variable beats the file.

Every run prints what the gate found, before the first test:

```
live tests: MSAT_LIVE_TESTS=on, provider=azure_openai, loaded /repo/.env, missing=nothing
```

If a run skips everything, that line says why. `missing=['OPENAI_API_KEY']` with
`provider=openai` when your `.env` is full of `AZURE_*` means `LLM_PROVIDER` is
not set. Point the tests at a different file with `MSAT_ENV_FILE=/path/to/.env`.

| provider | needs |
|---|---|
| `openai` (default) | `OPENAI_API_KEY` |
| `azure_openai` | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `OPENAI_API_VERSION` |

`OPENAI_API_VERSION` is required for Azure on purpose: without one the call fails
with an error about the deployment, which sends you looking in the wrong place.

## Every run writes what was said

```
conversations written to results/live/2026-08-10T09-26-23Z
```

The pass/fail is a summary; the exchange is the evidence. Each run leaves a
`transcript.md` to read and a `run.json` to diff against the previous one, plus
`results/live/latest.md`. Failures are kept and marked — a transcript is a better
bug report than a traceback when the thing that failed was a judgement.

The run directories are gitignored; `results/README.md` says how to keep one
deliberately, and `MSAT_RESULTS_DIR` writes them elsewhere.

## What is here

| | |
|---|---|
| `test_guard_detection.py` | Is this turn safety, a request for a person, voicemail, do-not-call or a pause? Asked twice — of the model alone, and of the whole guard |
| `test_turn_reading.py` | Does the extractor record what the member said, and nothing they did not? |
| `test_full_turns.py` | Do the two model calls compose — guard first, extractor only if it let the turn through? |
| `test_full_calls.py` | **Whole calls**, greeting to closing line — every question, the real planner, the disposition that came out |
| `scenarios/calls.json` | The complete calls, and what each must end as |
| `scenarios/guards.json` | The turns, and what each should be decided as |
| `scenarios/turns.json` | The turns, and what should be recorded from each |

The fallback is tested in `tests/test_guard_fallback.py`, deliberately *outside*
this directory: what it protects is the day the provider is gone, so it needs no
credentials and runs on every `pytest`. It reads the same scenario files, so the
two cannot drift.

## Adding a scenario

Add an object to the list in the relevant `scenarios/*.json`. No Python changes,
and no need to know pytest. Give it an `id` nobody else has and a `why` saying
what it is protecting — the `why` is printed when it fails, and a failure message
that explains the stakes is worth more than one that reports a mismatch.

## Two expectations per guard scenario

```json
"expect_model": "safeguarding",
"expect_call":  "safeguarding"
```

- `expect_model` is what the model alone makes of the turn. A failure here is a
  prompt problem; `prompts/detect_guards.system.md` is where it is fixed.
- `expect_call` is what the call does — patterns and precedence included. A
  failure here that `expect_model` passed is a composition problem;
  `core/guards.py` is where that is fixed.

They match in every scenario but one. `cost.fallen_behind_trips_the_floor` is a
member saying they have *fallen behind with the reading*, which the safeguarding
pattern matches because it is looking for a member who has had a fall. The model
clears it and the pattern floor overrules the model, so that member is handed to
a human and their answer to question 1 is lost. That is recorded as a cost rather
than quietly expected away — see the note in the scenario itself.

## These tests are not deterministic

A model can answer the same turn differently twice. That is a property of the
thing being tested, not a flaw in the test:

- **A safeguarding scenario that fails is never a flake.** Treat it as a
  regression in the prompt and fix the prompt.
- **Any other scenario that fails once** is worth re-running with
  `MSAT_LIVE_REPEAT=5` before changing anything. If it is right four times in
  five it is not right; the prompt needs the distinction spelled out.
- **Do not loosen an assertion to make a run green.** The negative scenarios —
  the ones expecting no guard and no recorded value — are the expensive half, and
  they are the half it is tempting to soften.

## Whole calls

`test_full_calls.py` runs a call from the greeting to the closing line. The agent
speaks, a scripted member answers whatever it was actually asked, and the loop
repeats until the call ends by itself — roughly ten agent turns, up to three
model calls each, driving the same loop `app_graph.py` runs in production.

Several things can only be seen here:

- question 1a is asked and 1b is not, decided by an answer given on the call
- question 5 appears for a high-risk member and is reported as **skipped** — not
  missing — for a rising one
- a safeguarding disclosure at question 2 stops the survey, keeps what came
  before it, and asks nothing after
- the disposition matches what happened rather than what was intended

The member's replies are keyed by the slot the agent is waiting on, never by
position, so the script answers the question actually put. If the planner asks
something the script has no reply for, the test says which question it was rather
than hanging — that is itself a finding.

`THIS MUST NEVER BE ASKED` is a real reply in the scripts. It is what a question
this member should never get would receive, so a planner that asks it produces a
named failure instead of a quietly plausible answer.

One rule when adding a call: **keep the gates unambiguous.** Identity and consent
are not what these scenarios test, and a gate that fails ends the call before the
interesting part and reports `ended_early`, hiding whatever the scenario was for.
Idiom, hesitation and oblique phrasing belong on the survey questions and the
guard interjections, where a misread is the finding rather than a wall in front
of one.
