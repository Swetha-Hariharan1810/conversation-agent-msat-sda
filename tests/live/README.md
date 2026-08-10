# Live tests

Everything here sends real requests to the configured provider. They are the only
tests that can tell you whether the prompts actually work — a stub can prove the
plumbing is right and nothing else.

```bash
# opt in, with credentials in the environment exactly as a call would have them
MSAT_LIVE_TESTS=1 uv run pytest tests/live -v

# just the guards, four times each, to see whether the answers are stable
MSAT_LIVE_TESTS=1 MSAT_LIVE_REPEAT=4 uv run pytest tests/live/test_guard_detection.py -v

# everything except the live tests (the default for anyone who has not opted in)
uv run pytest -m "not live"
```

Without `MSAT_LIVE_TESTS=1` the whole directory skips and says so. With the flag
but no credentials it skips and names the missing variable, rather than failing
as though the prompt were wrong.

## What is here

| | |
|---|---|
| `test_guard_detection.py` | Is this turn safety, a request for a person, voicemail, do-not-call or a pause? Asked twice — of the model alone, and of the whole guard |
| `test_turn_reading.py` | Does the extractor record what the member said, and nothing they did not? |
| `test_full_turns.py` | Do the two model calls compose — guard first, extractor only if it let the turn through? |
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
