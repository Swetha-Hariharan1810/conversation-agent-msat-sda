# `e24_direct_client.py`, explained simply

The script is a **robot that takes an Expert24 quiz for you**. It phones
Expert24, asks for a question, shows it to you, sends back your answer, and
repeats until the quiz ends. Then it asks for the full list of answers.

Part 1 explains the code block by block. Part 2 shows the actual calls from a
real UAT run, with each payload and response.

Related guides: [`EXPERT24_API_README.md`](EXPERT24_API_README.md) ·
[`CURL_README.md`](CURL_README.md) · [`POSTMAN_README.md`](POSTMAN_README.md)

---

## Part 1: What each block of code does

### Top of the file: the label

```python
# requires-python = ">=3.8"
# dependencies = []
```

This says the script needs Python 3.8 or newer and **no extra packages**.
That's why it runs with no virtual environment and no `pip install`.

### Settings

```python
API_ROOT = "/webbuilder/TraversalService"
DEFAULT_BASE_URL = "http://localhost:4200"
DEFAULT_TIMEOUT = 60
```

| Setting | Meaning |
|---|---|
| `API_ROOT` | The part of every Expert24 URL that never changes. |
| `DEFAULT_BASE_URL` | Where to send calls if you don't say otherwise. Override it with `--base-url https://aph-uat.expert-24.net`. |
| `DEFAULT_TIMEOUT` | Wait up to 60 seconds for an answer before giving up. |

### `E24Error`

A special error type. When something goes wrong, the script prints a **friendly
message** instead of a long Python crash.

### `E24DirectClient`: the phone

This class knows how to call Expert24.

- **`__init__`** remembers the address and timeout. With `--insecure`, it also
  skips certificate checks.
- **`_url`** builds the full address:
  `https://aph-uat.expert-24.net` + `/webbuilder/TraversalService` + `/Member`
- **`_call`** does the actual calling. It:
  1. Builds the URL.
  2. For POST calls, attaches the body, using `{}` if there's none.
  3. Adds two headers: `Content-Type: application/json` and
     `Accept: application/json`.
  4. Sends the request.
  5. If Expert24 returns an error (404, 500…), it raises a friendly message
     explaining it (`_explain_status`).
  6. If the reply is empty or not JSON, it says so. If it got a web page instead
     of data, it hints that the URL is wrong.
  7. Otherwise it turns the JSON text into a Python dictionary and returns it.

### The five "buttons" on the phone

| Function | Calls | Plain meaning |
|---|---|---|
| `start` | `POST /Member` | "Begin a quiz for this person" |
| `first_question` | `POST /First/...` | "Give me question 1" |
| `next_question` | `POST /Next/...` | "Here's my answer, give me the next one" |
| `previous_question` | `GET /Previous/...` | "Go back one question" (see [Previous](#previous-go-back-one-question) below) |
| `qa` | `GET /QA/...` | "Show me everything I answered" |

`_esc` makes IDs safe to put in a URL, so a `/` or space in an ID can't break
it.

### Helpers that read or write the JSON

| Function | Plain meaning |
|---|---|
| `build_answer_body` | Turns your choice into the answer format: `{"1": ""}` for a picked option, `{"1": "dscvds"}` for typed text, `{}` for nothing. |
| `is_complete` | "Is the quiz over?" Yes if there's a `Report`, or if `AlgoName` is empty. |
| `start_handles` | Pulls **TraversalID** and **MemberID** out of the start reply. If they're missing, explains why. |
| `plain` | Strips HTML like `<b>` from question text so it looks clean in the terminal. |
| `describe_question` | Prints the question and its `[1] [2]` choices, and works out the type: `single` (radio), `multi` (checkbox), `value` (type something) or `none` (no answers). |
| `summarise_qa` | Prints the final Q: / A: list. |
| `summarise_conclusions` | Prints results such as `[Default] 2026.03.13.1`. |

### The commands you can type

| Command | Function | What it does |
|---|---|---|
| `run` | `cmd_run` | **Everything:** start, all questions, QA. |
| `start` | `cmd_start` | Only begins a quiz and prints the two IDs. |
| `question` | `cmd_question` | One question: First if you don't give `--node-id`, otherwise Next. |
| `qa` | `cmd_qa` | Only prints the answer list. |

Helpers used by these commands:

- `read_prepop` reads optional member facts from `--prepop` or
  `--prepop-file`.
- `prompt_answer` asks you for input: "Choose a number >" or "Value >". It
  keeps asking until the input is valid.
- `auto_answer` (with `--auto`) always picks option 1, or types `"1"` for text
  questions.
- `emit` (with `--raw`) prints the full JSON.

### `build_parser` and `main`: the front door

- `build_parser` defines every option (`--base-url`, `--member-id`,
  `--algorithm-id`, `--auto`, `--save`, …). Several can also come from
  environment variables such as `E24_MEMBER_ID`.
- `main` reads your command, checks nothing required is missing, creates the
  "phone", runs the command, and turns errors into friendly messages. Ctrl+C
  prints "Stopped."

---

## Part 2: A real run, call by call

The run used this command:

```bash
python3 scripts/e24_direct_client.py run \
  --base-url https://aph-uat.expert-24.net \
  --member-id ABC_TMJarrett --algorithm-id 10657
```

Every call sends these two headers:

```
Content-Type: application/json
Accept: application/json
```

### Call 1: START

**Request**

```
POST https://aph-uat.expert-24.net/webbuilder/TraversalService/Member

{"@UserID": "ABC_TMJarrett", "callback": "raw"}
```

There's no `Prepop` because `--prepop` wasn't passed.

**Response**

```json
{
  "Table": [
    { "TraversalID": "cd6ed911-5ba5-40ac-a72d-ad3650516b50", "MemberID": "1492375", ... }
  ],
  ...
}
```

The script printed:
`traversal id cd6ed911-5ba5-40ac-a72d-ad3650516b50, e24 member id 1492375`

### Call 2: FIRST

**Request**

```
POST https://aph-uat.expert-24.net/webbuilder/TraversalService/First/cd6ed911-5ba5-40ac-a72d-ad3650516b50/1492375/10657/0?Language=MEMBER

{}
```

**Response**

```json
{
  "AlgoID": 10657,
  "AlgoName": "Healthy Aging Member Satisfaction Survey",
  "NodeID": 487,
  "Questions": [
    { "DisplayText": "Please tell us about your experiences with the Smart Step Aging in Place service by completing a short satisfaction survey.",
      "Answers": [] }
  ],
  ...
}
```

There are no answers, so the type is `none` and the script said "press Enter to
continue". Anything typed there is ignored.

### Calls 3 to 12: NEXT, ten times

Each request goes to:

```
POST https://aph-uat.expert-24.net/webbuilder/TraversalService/Next/cd6ed911-5ba5-40ac-a72d-ad3650516b50/1492375/10657/{node}
```

The node in the URL is the question **being answered**. The response brings
the **next** question.

| # | Node in URL | Body sent | Next question in the response |
|---|---|---|---|
| 1 | 487 | `{}` | 908: "Were you able to review any of the program resources…?" `[1] Yes [2] No` |
| 2 | 908 | `{"1": ""}` | 863: "How helpful were the resources…?" `[1] Extremely Helpful [2] Somewhat Helpful [3] Not Very Helpful [4] Definitely Not Helpful` |
| 3 | 863 | `{"1": ""}` | 903: "Please tell us what you liked most…" `[1] (text)` |
| 4 | 903 | `{"1": "dscvds"}` | 955: "What changes or additions would you like…?" `[1] (text)` |
| 5 | 955 | `{"1": "gfgd"}` | 966: "…would you recommend our program…?" `[1] Yes [2] No` |
| 6 | 966 | `{"1": ""}` | 889: "Action is looking for collection of Risk Level of 3…" `[1] Yes [2] No` |
| 7 | 889 | `{"1": ""}` | 894: "Were program staff helpful and knowledgeable…?" `[1] Yes [2] No` |
| 8 | 894 | `{"1": ""}` | 881: "How would you rate your experience with the program overall?" `[1] Extremely Helpful …` |
| 9 | 881 | `{"1": ""}` | 876: "Thank you for answering our questions…" *(no answers)* |
| 10 | 876 | `{}` | **the finished response** |

A typical question response, e.g. after call #1:

```json
{
  "AlgoID": 10657,
  "AlgoName": "Healthy Aging Member Satisfaction Survey",
  "NodeID": 908,
  "Questions": [
    { "DisplayText": "Were you able to review any of the program resources such as action plans, articles, videos, or websites?",
      "Answers": [
        { "Index": "1", "DisplayText": "Yes", "ControlType": "radio", ... },
        { "Index": "2", "DisplayText": "No",  "ControlType": "radio", ... }
      ] }
  ],
  ...
}
```

A typed-text question, e.g. after call #3:

```json
{
  "AlgoID": 10657,
  "AlgoName": "Healthy Aging Member Satisfaction Survey",
  "NodeID": 903,
  "Questions": [
    { "DisplayText": "Please tell us what you liked most about the program. If you don’t have feedback, please enter no or none.",
      "Answers": [
        { "Index": "1", "DisplayText": "", "ControlType": "...", "ControlSubType": "text", ... }
      ] }
  ],
  ...
}
```

**The finished response** (after call #10):

```json
{
  "AlgoName": "",
  "Conclusions": [
    { "Category": "Default", "DisplayText": "2026.03.13.1", ... }
  ],
  ...
}
```

`AlgoName` is empty, so `is_complete` returns true and the script printed
"Finished after 10 question(s)" and `[Default] 2026.03.13.1`, the content
version.

### Last call: QA

**Request**

```
GET https://aph-uat.expert-24.net/webbuilder/TraversalService/QA/cd6ed911-5ba5-40ac-a72d-ad3650516b50
```

No body.

**Response**

```json
{
  "Table": [
    { "Question": "Please tell us about your experiences with the Smart Step ...", "Answer": "Next >", ... },
    { "Question": "Were you able to review any of the program resources ...?",     "Answer": "Yes", ... },
    { "Question": "How helpful were the resources ...?",                              "Answer": "Extremely Helpful", ... },
    { "Question": "Please tell us what you liked most about the program ...",        "SValue": "dscvds", ... },
    { "Question": "We value your feedback! What changes or additions ...?",          "SValue": "gfgd", ... },
    { "Question": "... would you recommend our program to people you know?",          "Answer": "Yes", ... },
    { "Question": "Action is looking for collection of Risk Level of 3 ...",         "Answer": "Yes", ... },
    { "Question": "Were program staff helpful and knowledgeable ...?",               "Answer": "Yes", ... },
    { "Question": "How would you rate your experience with the program overall?",   "Answer": "Extremely Helpful", ... },
    { "Question": "Thank you for answering our questions ...",                         "Answer": "Next >", ... }
  ]
}
```

---

## Previous: go back one question

`previous_question` is in the script, but **no command uses it**: `run`,
`start`, `question` and `qa` never call it. It also **wasn't part of the run
above**, so the example below shows what to **expect**, based on the code and
the shape FIRST and NEXT return. It isn't a captured response.

### What it does

It moves the quiz back one step and returns **the question before the current
one**, in the same shape as FIRST and NEXT.

### Request

```
GET https://aph-uat.expert-24.net/webbuilder/TraversalService/Previous/cd6ed911-5ba5-40ac-a72d-ad3650516b50
Content-Type: application/json
Accept: application/json
```

- Only the **traversal ID** goes in the URL. There's no member ID, algorithm or
  node.
- **No body.** It's a GET.

### Example

Say you've answered node 908 ("Yes") and are now looking at **node 863** ("How
helpful were the resources…?"). Calling Previous should take you back to
**node 908**:

```json
{
  "AlgoID": 10657,
  "AlgoName": "Healthy Aging Member Satisfaction Survey",
  "NodeID": 908,
  "Questions": [
    { "DisplayText": "Were you able to review any of the program resources such as action plans, articles, videos, or websites?",
      "Answers": [
        { "Index": "1", "DisplayText": "Yes", "ControlType": "radio", "isChecked": ..., ... },
        { "Index": "2", "DisplayText": "No",  "ControlType": "radio", "isChecked": ..., ... }
      ] }
  ],
  ...
}
```

Then answer it again with NEXT using **the node Previous returned**:

```
POST .../Next/cd6ed911-5ba5-40ac-a72d-ad3650516b50/1492375/10657/908

{"2": ""}        ← e.g. change the answer to "No"
```

`isChecked` may show the answer given earlier. Check it in your own response.

### How to call it

With curl:

```bash
B=https://aph-uat.expert-24.net/webbuilder/TraversalService
curl -sS "$B/Previous/cd6ed911-5ba5-40ac-a72d-ad3650516b50" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  | python3 -m json.tool
```

With the script's own code, from the repo root:

```bash
python3 -c '
import json, sys
sys.path.insert(0, "scripts")
from e24_direct_client import E24DirectClient
c = E24DirectClient("https://aph-uat.expert-24.net")
print(json.dumps(c.previous_question("cd6ed911-5ba5-40ac-a72d-ad3650516b50"), indent=2))
'
```

Use the traversal ID from **your own** Start. The one above belongs to an
earlier run.

---

## About these responses

- The values in Part 2 (IDs, node numbers, question text, answer choices,
  conclusion, QA answers) are **real, taken from the run's terminal output**.
- The script only prints selected fields, so `...` marks fields that exist but
  weren't printed.
- These details are best readings, not directly seen:
  - the answer `Index` values, inferred from the `[1] [2]` labels;
  - `ControlType` for the text questions;
  - whether typed text comes back in QA's `SValue` or `Answer`.
- The **Previous** response is expected, not captured.

To see the complete real JSON, rerun with `--save` or `--raw`:

```bash
python3 scripts/e24_direct_client.py run --base-url https://aph-uat.expert-24.net \
  --member-id ABC_TMJarrett --algorithm-id 10657 --save result.json
```

`result.json` holds the full final response and the full QA response. You can
also add `--raw` to `start`, `question` or `qa` to print everything Expert24
sends back for that call.
