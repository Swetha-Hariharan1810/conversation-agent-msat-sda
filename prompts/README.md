# Prompts

Every word this project sends to a model. Nothing in Python holds prompt text —
if the agent says something to a model, it is in a file here.

You can edit these without touching code. What you cannot do is change which
`{placeholders}` a prompt takes: those are declared in
`msat_flow/llm/prompts.py` under `CONTRACT`, and a file whose placeholders do not
match its declaration is refused at load with a message naming the mismatch. That
is deliberate — a mistyped `{slot}` would otherwise reach a live call as a
literal brace, and a prompt that quietly stopped receiving the answer options
would have the agent inventing them.

Braces are therefore reserved. A `{` in a prompt file is read as a placeholder,
so a JSON example pasted in here fails the test suite rather than the call.

## What is here

| File | Sent when |
|---|---|
| `detect_guards.system.md` | Deciding whether a turn is one the survey cannot carry on through — safety, a request for a person, voicemail, do-not-call, a pause |
| `detect_guards.user.md` | …with the last thing said and the member's reply, and nothing else |
| `extract_turn.system.md` | Reading one member turn — the rules for what may be recorded |
| `extract_turn.user.md` | …with this call's questions, the last thing said, and the member's reply |
| `speak_line.system.md` | Saying one line — who Ida is, and the hard rules on wording |
| `speak_line.user.md` | …with the goal for this turn, and whichever sections below apply |
| `speak_line.reference.md` | The script's own wording for this turn, to adapt |
| `speak_line.preamble.md` | The survey's opening line, led into the first question |
| `speak_line.options.md` | The answer options to read out |
| `speak_line.values.md` | Values from the work item the turn may state (the member's name) |
| `speak_line.context.md` | What the member just said |
| `speak_line.acknowledge.md` | A one-line acknowledgement of something we cannot act on |
| `speak_line.retry.md` | Ask again — the answer did not land, and why |
| `speak_line.attempt.md` | How many attempts this question has had. Only sent once one has been spent — a question the member asked us to repeat is put again without charging one |
| `simulated_member.system.md` | The **member** in a graded run, not the agent |
| `personas/*.md` | How that simulated member delivers their answers |

Which of the optional `speak_line.*` sections appear, and in what order, is
decided in `msat_flow/llm/response_generator.py`. A file here is a piece of
wording, not a program.

## What is *not* here

The words the agent says to the **member** are not prompts and are not in this
folder. They come from the approved document, via `data/msat_script.json`, and
the handful of lines the document does not cover are declared in
`data/slot_map.json` under `off_script`. Putting approved call wording in here
would put it one edit away from being paraphrased by a model.

So: `prompts/` is what we say to the model. `data/` is what we say to the member.

## Personas

`personas/` holds the delivery styles for the simulated member in
`scripts/live_eval.py`. Adding one is dropping a file in — the filename stem is
the name you pass to `--persona`, and the contents are the instruction. No code
change.

A persona may only change *how* the member speaks. The answers themselves are
generated from the spec, identically for every persona, because a graded run
only means something if a differently-delivered call has to record the same
survey.
