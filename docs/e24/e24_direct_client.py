#!/usr/bin/env python3
# /// script
# requires-python = ">=3.8"
# dependencies = []
# ///
"""Drive Expert24's TraversalService directly: start, question, QA.

This is the *direct* Expert24 API (`/webbuilder/TraversalService/...`), which is
what the assessment control calls when "Use Expert24 Direct APIs" is ticked. It
is a different API from the one `e24_proxy_client.py` speaks
(`/api/E24Proxy/...`, the Sagility Clinical Content Service). Use whichever
matches the mode you are running in.

Three calls carry an assessment from beginning to end:

    start     POST /webbuilder/TraversalService/Member
              -> a traversal id and an Expert24 member id, the two handles
                 every later call needs

    question  POST /webbuilder/TraversalService/First/{tid}/{mid}/{algo}/0
              POST /webbuilder/TraversalService/Next/{tid}/{mid}/{algo}/{node}
              -> one question at a time; the assessment is over when the
                 response carries no AlgoName

    qa        GET  /webbuilder/TraversalService/QA/{tid}
              -> every question and answer recorded for the traversal

Point --base-url at whatever can reach Expert24. Because a browser cannot call
Expert24 across origins, the normal local setup is the Angular dev server with
proxy.config.json forwarding /webbuilder, which is why the default is
http://localhost:4200. Against a host that allows it you can pass the Expert24
URL directly instead.

    python3 scripts/e24_direct_client.py run --member-id ABC_TMJarrett --algorithm-id 10657
    python3 scripts/e24_direct_client.py start --member-id ABC_TMJarrett
    python3 scripts/e24_direct_client.py qa --traversal-id 12345
"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

API_ROOT = "/webbuilder/TraversalService"
DEFAULT_BASE_URL = "http://localhost:4200"
DEFAULT_TIMEOUT = 60

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------

class E24Error(Exception):
    """Anything that stops the run, already phrased for a human."""


class E24DirectClient:

    def __init__(self, base_url, timeout=DEFAULT_TIMEOUT, verify_tls=True, verbose=False):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.verbose = verbose
        self._ctx = None
        if not verify_tls:
            self._ctx = ssl.create_default_context()
            self._ctx.check_hostname = False
            self._ctx.verify_mode = ssl.CERT_NONE

    # -- plumbing ----------------------------------------------------------

    def _url(self, path, query=None):
        url = f"{self.base_url}{API_ROOT}{path}"
        if query:
            clean = {k: str(v) for k, v in query.items() if v not in (None, "")}
            if clean:
                url = f"{url}?{urllib.parse.urlencode(clean)}"
        return url

    def _call(self, method, path, query=None, body=None):
        url = self._url(path, query)
        # The control always sends application/json, even where the body is the
        # empty object. Matching that matters: the content type is what makes a
        # browser preflight the request, and what the server negotiates on.
        data = None
        if method == "POST":
            data = (body if body is not None else "{}").encode("utf-8")

        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")

        if self.verbose:
            print(f"  -> {method} {url}", file=sys.stderr)
            if data:
                print(f"     body: {data.decode('utf-8')}", file=sys.stderr)

        try:
            kwargs = {"timeout": self.timeout}
            if self._ctx is not None:
                kwargs["context"] = self._ctx
            with urllib.request.urlopen(request, **kwargs) as response:
                raw = response.read().decode("utf-8", errors="replace")
                status = response.status
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise E24Error(
                f"HTTP {exc.code} from {url}\n"
                f"  {detail or exc.reason}\n"
                f"  {self._explain_status(exc.code)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise E24Error(
                f"Could not reach {url}\n"
                f"  reason: {exc.reason}\n"
                "  Is the dev server running, and can this machine reach Expert24?"
            ) from exc

        if self.verbose:
            print(f"  <- {status} ({len(raw)} bytes)", file=sys.stderr)

        if not raw.strip():
            raise E24Error(f"{url} returned an empty body (HTTP {status}).")

        try:
            return json.loads(raw)
        except ValueError:
            # The single most common cause is pointing --base-url at a web page
            # rather than at something that forwards /webbuilder.
            head = raw.strip()[:200]
            hint = ""
            if head.lower().startswith(("<!doctype", "<html")):
                hint = ("\n  That is an HTML page, not the API. If --base-url is the "
                        "Angular dev server,\n  check that proxy.config.json is in "
                        "place and ng serve picked it up.")
            raise E24Error(f"{url} did not return JSON.\n  first bytes: {head}{hint}")

    @staticmethod
    def _explain_status(code):
        return {
            401: "Expert24 wants credentials this script is not sending.",
            403: "Expert24 refused the request for this member or environment.",
            404: "Wrong path or wrong base URL - nothing serves that route.",
            500: "Expert24 raised an error; the traversal or prepop may be invalid.",
            502: "The proxy could not reach Expert24.",
            504: "The proxy timed out waiting for Expert24.",
        }.get(code, "")

    # -- the three calls ---------------------------------------------------

    def start(self, member_id, prepop=None):
        """POST /Member - open a traversal for this member."""
        payload = {"@UserID": member_id, "callback": "raw"}
        if prepop:
            payload["Prepop"] = prepop
        return self._call("POST", "/Member", body=json.dumps(payload))

    def first_question(self, traversal_id, e24_member_id, algorithm_id, language="MEMBER"):
        """POST /First - the opening question of an assessment."""
        path = f"/First/{_esc(traversal_id)}/{_esc(e24_member_id)}/{_esc(algorithm_id)}/0"
        return self._call("POST", path, query={"Language": language})

    def next_question(self, traversal_id, e24_member_id, algorithm_id,
                      previous_node_id, answers=None):
        """POST /Next - submit answers to one question, receive the following one."""
        path = (f"/Next/{_esc(traversal_id)}/{_esc(e24_member_id)}"
                f"/{_esc(algorithm_id)}/{previous_node_id}")
        return self._call("POST", path, body=build_answer_body(answers))

    def previous_question(self, traversal_id):
        """GET /Previous - step back one question."""
        return self._call("GET", f"/Previous/{_esc(traversal_id)}")

    def qa(self, traversal_id):
        """GET /QA - every question and answer recorded for this traversal."""
        return self._call("GET", f"/QA/{_esc(traversal_id)}")


def _esc(value):
    return urllib.parse.quote(str(value), safe="")


# --------------------------------------------------------------------------
# Request and response shapes
# --------------------------------------------------------------------------

def build_answer_body(answers):
    """Build the /Next body exactly as the shipped control builds it.

    Keys are the Index values Expert24 gave in the question. A selected radio or
    checkbox is the empty string; a value-entry answer carries its text. So one
    selected radio is {"1": ""}, two ticked checkboxes {"1": "", "2": ""}, and a
    typed weight {"1": "180"}.
    """
    if not answers:
        return "{}"
    return json.dumps({str(k): ("" if v is None else str(v)) for k, v in answers.items()})


def is_complete(response):
    """An assessment is over when Expert24 stops naming an algorithm."""
    if response.get("Report"):
        return True
    return not response.get("AlgoName")


def start_handles(response):
    """Pull the traversal id and Expert24 member id out of a start response."""
    table = response.get("Table") or []
    if not table:
        raise E24Error(
            "The start response carried no Table entry, so there is no traversal to "
            "continue.\n  Expert24 usually means the member id is unknown in this "
            "environment, or a\n  required prepop value is missing."
        )
    row = table[0]
    traversal_id = row.get("TraversalID")
    member_id = row.get("MemberID")
    if not traversal_id or not member_id:
        raise E24Error(f"The start response is missing TraversalID or MemberID: {row}")
    return str(traversal_id), str(member_id)


TAG = re.compile(r"<[^>]+>")


SPACE_BEFORE_PUNCT = re.compile(r"\s+([,.;:!?%)\]])")


def plain(text):
    """Expert24 question text carries HTML; terminals do not."""
    if not text:
        return ""
    # Tags become spaces so words either side stay apart, which leaves a gap
    # before trailing punctuation: "apply to <b>you</b>?" -> "apply to you ?".
    stripped = " ".join(TAG.sub(" ", str(text)).split())
    return SPACE_BEFORE_PUNCT.sub(r"\1", stripped)


def describe_question(response):
    """One question rendered for a terminal, plus what is needed to answer it."""
    questions = response.get("Questions") or []
    if not questions:
        return "(no question in this response)", [], None

    question = questions[0]
    node_id = response.get("NodeID")
    lines = []

    title = plain(question.get("Title"))
    if title:
        lines.append(title)
    lines.append(plain(question.get("DisplayText")) or "(untitled question)")

    answers = question.get("Answers") or []
    for answer in answers:
        label = plain(answer.get("DisplayText")) or "(unlabelled)"
        subtype = answer.get("ControlSubType") or ""
        suffix = f" ({subtype})" if subtype else ""
        lines.append(f"  [{answer.get('Index')}] {label}{suffix}")

    kinds = {(a.get("ControlType") or "").lower() for a in answers}
    if "checkbox" in kinds:
        kind = "multi"
    elif "radio" in kinds:
        kind = "single"
    elif kinds:
        kind = "value"
    else:
        kind = "none"

    lines.append("")
    lines.append(f"  node={node_id}  algo={response.get('AlgoID')}  type={kind}")
    return "\n".join(lines), answers, kind


def summarise_qa(payload):
    rows = payload.get("Table") or []
    if not rows:
        return "The QA endpoint returned no recorded answers."
    out = [f"{len(rows)} recorded answer(s):", ""]
    for row in rows:
        value = plain(row.get("SValue"))
        answer = plain(row.get("Answer"))
        shown = f"{value} {answer}".strip() if value else answer
        out.append(f"  Q: {plain(row.get('Question'))}")
        out.append(f"  A: {shown or '(blank)'}")
        out.append("")
    return "\n".join(out)


def summarise_conclusions(response):
    conclusions = response.get("Conclusions") or []
    if not conclusions:
        return ""
    out = [f"Conclusions: {len(conclusions)}"]
    for item in conclusions:
        out.append(f"  [{item.get('Category') or '?'}] {plain(item.get('DisplayText'))}")
    return "\n".join(out)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def read_prepop(args):
    if args.prepop_file:
        try:
            with open(args.prepop_file, encoding="utf-8") as handle:
                return json.load(handle)
        except OSError as exc:
            raise E24Error(f"Could not read {args.prepop_file}: {exc}") from exc
        except ValueError as exc:
            raise E24Error(f"{args.prepop_file} is not valid JSON: {exc}") from exc
    if args.prepop:
        try:
            return json.loads(args.prepop)
        except ValueError as exc:
            raise E24Error(f"--prepop is not valid JSON: {exc}") from exc
    return None


def emit(payload, raw):
    if raw:
        print(json.dumps(payload, indent=2))


def cmd_start(client, args):
    response = client.start(args.member_id, read_prepop(args))
    traversal_id, member_id = start_handles(response)
    print(f"traversal id  : {traversal_id}")
    print(f"e24 member id : {member_id}")
    print()
    print("Both are needed by every later call. Pass them to 'question' and 'qa'.")
    emit(response, args.raw)
    return EXIT_OK


def cmd_question(client, args):
    if args.node_id is None:
        response = client.first_question(
            args.traversal_id, args.e24_member_id, args.algorithm_id, args.language)
    else:
        answers = {}
        for pair in args.answer or []:
            if "=" in pair:
                key, value = pair.split("=", 1)
            else:
                key, value = pair, ""
            answers[key.strip()] = value
        response = client.next_question(
            args.traversal_id, args.e24_member_id, args.algorithm_id,
            args.node_id, answers)

    if response.get("Error"):
        print(f"Expert24 reported: {response['Error']}")
        return EXIT_FAILED

    if is_complete(response):
        print("The assessment is complete - no further questions.")
        conclusions = summarise_conclusions(response)
        if conclusions:
            print()
            print(conclusions)
    else:
        text, _, _ = describe_question(response)
        print(text)
    emit(response, args.raw)
    return EXIT_OK


def cmd_qa(client, args):
    response = client.qa(args.traversal_id)
    print(summarise_qa(response))
    emit(response, args.raw)
    return EXIT_OK


def cmd_run(client, args):
    """All three calls in sequence: start, every question, then QA."""
    prepop = read_prepop(args)

    print(f"Expert24 via : {client.base_url}{API_ROOT}")
    print(f"Member       : {args.member_id}")
    print(f"Assessment   : {args.algorithm_id}")
    print()

    print("[1] POST /Member ...")
    start = client.start(args.member_id, prepop)
    traversal_id, e24_member_id = start_handles(start)
    print(f"    traversal id {traversal_id}, e24 member id {e24_member_id}")
    print()

    print("[2] POST /First ...")
    response = client.first_question(traversal_id, e24_member_id,
                                     args.algorithm_id, args.language)
    if response.get("Error"):
        raise E24Error(f"Expert24 reported: {response['Error']}")
    if not response.get("AlgoName"):
        raise E24Error(
            "Expert24 returned no assessment for that algorithm id.\n"
            "  Check the id exists in this environment and the member may take it."
        )
    print(f"    assessment '{response['AlgoName']}'")
    print()

    answered = 0
    while not is_complete(response):
        text, answers, kind = describe_question(response)
        print("-" * 70)
        print(text)
        print("-" * 70)

        if args.auto:
            chosen = auto_answer(answers, kind)
            print(f"  auto-answering: {chosen}")
        else:
            chosen = prompt_answer(answers, kind)

        node_id = response.get("NodeID")
        algo_id = response.get("AlgoID", args.algorithm_id)
        print(f"[3] POST /Next/{traversal_id}/{e24_member_id}/{algo_id}/{node_id} ...")
        response = client.next_question(traversal_id, e24_member_id,
                                        algo_id, node_id, chosen)
        if response.get("Error"):
            raise E24Error(f"Expert24 reported: {response['Error']}")
        answered += 1
        if args.max_questions and answered >= args.max_questions:
            print(f"\nStopping after {answered} question(s) as asked.")
            break
        print()

    print("=" * 70)
    print(f"Finished after {answered} question(s).")
    print("=" * 70)
    print()

    conclusions = summarise_conclusions(response)
    if conclusions:
        print(conclusions)
        print()

    print(f"[4] GET /QA/{traversal_id} ...")
    qa_results = client.qa(traversal_id)
    print(summarise_qa(qa_results))

    if args.save:
        bundle = {
            "traversalId": traversal_id,
            "e24MemberId": e24_member_id,
            "algorithmId": args.algorithm_id,
            "final": response,
            "qa": qa_results,
        }
        with open(args.save, "w", encoding="utf-8") as handle:
            json.dump(bundle, handle, indent=2)
        print(f"\nWritten to {args.save}")

    return EXIT_OK


def auto_answer(answers, kind):
    """Pick the first option, so a run can be scripted end to end."""
    if not answers:
        return {}
    first = str(answers[0].get("Index"))
    if kind == "value":
        return {first: "1"}
    return {first: ""}


def prompt_answer(answers, kind):
    if not answers:
        input("  (no answers - press Enter to continue) ")
        return {}

    valid = {str(a.get("Index")) for a in answers}
    while True:
        if kind == "multi":
            reply = input("  Choose number(s), comma separated > ").strip()
            picks = [p.strip() for p in reply.split(",") if p.strip()]
            if picks and all(p in valid for p in picks):
                return {p: "" for p in picks}
        elif kind == "single":
            reply = input("  Choose a number > ").strip()
            if reply in valid:
                return {reply: ""}
        else:
            label = plain(answers[0].get("DisplayText")) or "Value"
            reply = input(f"  {label} > ").strip()
            if reply:
                return {str(answers[0].get("Index")): reply}
        print("  Not one of the options above - try again.")


# --------------------------------------------------------------------------
# Argument parsing
# --------------------------------------------------------------------------

def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default=os.environ.get("E24_DIRECT_URL", DEFAULT_BASE_URL),
                        help="host that can reach Expert24; the Angular dev server "
                             f"by default (env E24_DIRECT_URL, default {DEFAULT_BASE_URL})")
    common.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT,
                        help=f"seconds per request (default {DEFAULT_TIMEOUT})")
    common.add_argument("--insecure", action="store_true",
                        help="skip TLS verification (self-signed internal hosts only)")
    common.add_argument("-v", "--verbose", action="store_true",
                        help="print each request and response on stderr")
    common.add_argument("--raw", action="store_true",
                        help="also print the raw JSON response")

    handles = argparse.ArgumentParser(add_help=False)
    handles.add_argument("--traversal-id", required=True, help="from the start response")
    handles.add_argument("--e24-member-id", required=True, help="from the start response")

    prepop = argparse.ArgumentParser(add_help=False)
    prepop.add_argument("--prepop", help="prepop facts as a JSON string")
    prepop.add_argument("--prepop-file", help="prepop facts from a JSON file")

    parser = argparse.ArgumentParser(
        prog="e24_direct_client.py",
        description="Start an Expert24 assessment, walk its questions, read back the QA.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "The three calls:\n"
            "  start     opens a traversal and returns the two ids everything else needs\n"
            "  question  fetches the first question, or submits answers and fetches the next\n"
            "  qa        reads back every question and answer for a traversal\n"
            "  run       does all of it in one go - start here\n"
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", parents=[common, prepop],
                           help="start, walk every question, then load the QA")
    p_run.add_argument("--member-id", default=os.environ.get("E24_MEMBER_ID"), required=False)
    p_run.add_argument("--algorithm-id", default=os.environ.get("E24_ALGORITHM_ID"), required=False)
    p_run.add_argument("--language", default=os.environ.get("E24_LANGUAGE", "MEMBER"),
                       choices=["MEMBER", "SPANISH"])
    p_run.add_argument("--auto", action="store_true",
                       help="answer every question with its first option (no prompts)")
    p_run.add_argument("--max-questions", type=int, default=0,
                       help="stop after this many questions (0 = until complete)")
    p_run.add_argument("--save", help="write the final response and QA to this file")
    p_run.set_defaults(func=cmd_run, needs=["member_id", "algorithm_id"])

    p_start = sub.add_parser("start", parents=[common, prepop],
                             help="POST /Member - open a traversal")
    p_start.add_argument("--member-id", default=os.environ.get("E24_MEMBER_ID"))
    p_start.set_defaults(func=cmd_start, needs=["member_id"])

    p_q = sub.add_parser("question", parents=[common, handles],
                         help="POST /First or /Next - fetch a question")
    p_q.add_argument("--algorithm-id", default=os.environ.get("E24_ALGORITHM_ID"))
    p_q.add_argument("--language", default=os.environ.get("E24_LANGUAGE", "MEMBER"),
                     choices=["MEMBER", "SPANISH"])
    p_q.add_argument("--node-id", type=int,
                     help="node just answered; omit for the first question")
    p_q.add_argument("--answer", action="append", metavar="INDEX[=VALUE]",
                     help="repeatable; '1' ticks option 1, '1=180' types a value")
    p_q.set_defaults(func=cmd_question, needs=["algorithm_id"])

    p_qa = sub.add_parser("qa", parents=[common],
                          help="GET /QA - read back the recorded answers")
    p_qa.add_argument("--traversal-id", required=True)
    p_qa.set_defaults(func=cmd_qa, needs=[])

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    missing = [f"--{n.replace('_', '-')}" for n in getattr(args, "needs", [])
               if not getattr(args, n, None)]
    if missing:
        parser.error("missing required option(s): " + ", ".join(missing)
                     + "\n  (or set the matching E24_* environment variable)")

    client = E24DirectClient(
        base_url=args.base_url,
        timeout=args.timeout,
        verify_tls=not args.insecure,
        verbose=args.verbose,
    )
    if args.insecure:
        print("warning: TLS verification is off", file=sys.stderr)

    try:
        return args.func(client, args)
    except E24Error as exc:
        print(f"\nerror: {exc}", file=sys.stderr)
        return EXIT_FAILED
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return EXIT_INTERRUPTED


if __name__ == "__main__":
    sys.exit(main())
