"""Load the prompts from ``prompts/``.

Every word this agent sends to a model lives in that folder, as plain Markdown a
non-engineer can read and edit. Nothing in Python holds prompt text.

The one thing code still owns is the *contract*: which placeholders each prompt
takes. ``CONTRACT`` below declares it, and a prompt is refused at load if its
placeholders do not match — so a renamed or mistyped ``{slot}`` fails a test
rather than reaching a live call as a literal brace, and a prompt cannot quietly
stop receiving the options it is supposed to read out.

Composition — which optional sections appear, and in what order — stays in
``response_generator.py``. A prompt file is a piece of wording, not a program.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from string import Formatter

PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts"
PERSONA_DIR = PROMPT_DIR / "personas"
SUFFIX = ".md"


class PromptError(ValueError):
    """A prompt file is missing, empty, or does not match its declared contract."""


# Prompt name -> the placeholders it must contain, exactly.
#
# Empty means the prompt takes none and is sent as written. Anything the model
# is told about the call arrives through one of these.
CONTRACT: dict[str, frozenset[str]] = {
    # Deciding whether one member turn trips a guard.
    "detect_guards.system": frozenset(),
    "detect_guards.user": frozenset({"last_agent", "member"}),
    # Reading one member turn.
    "extract_turn.system": frozenset(),
    "extract_turn.user": frozenset({"slots", "last_agent", "member"}),
    # Saying one line.
    "speak_line.system": frozenset(),
    "speak_line.user": frozenset({"goal", "sections"}),
    "speak_line.reference": frozenset({"text"}),
    "speak_line.preamble": frozenset({"text"}),
    "speak_line.options": frozenset({"options"}),
    "speak_line.values": frozenset({"values"}),
    "speak_line.context": frozenset({"member"}),
    "speak_line.acknowledge": frozenset({"ack"}),
    "speak_line.retry": frozenset({"slot", "reason", "attempt", "limit"}),
    # The simulated member in scripts/live_call.py and scripts/live_eval.py.
    # Not part of the agent; it is the other side of a graded call.
    "simulated_member.system": frozenset({"name", "answers", "persona"}),
}


def path_for(name: str) -> Path:
    return PROMPT_DIR / f"{name}{SUFFIX}"


def placeholders(template: str) -> frozenset[str]:
    """The ``{names}`` a template contains.

    A stray brace shows up here as an unexpected placeholder, which is what makes
    a JSON example pasted into a prompt file fail loudly instead of blowing up
    ``str.format`` mid-call.
    """
    return frozenset(field for _, field, _, _ in Formatter().parse(template) if field)


@lru_cache(maxsize=None)
def load(name: str) -> str:
    """The prompt's text, validated against its declared contract."""
    if name not in CONTRACT:
        raise PromptError(f"unknown prompt {name!r}; prompts/ declares {sorted(CONTRACT)}")
    path = path_for(name)
    try:
        text = path.read_text(encoding="utf-8").rstrip("\n")
    except FileNotFoundError as exc:
        raise PromptError(f"prompt {name!r} is declared but {path.name} does not exist") from exc
    if not text.strip():
        raise PromptError(f"prompt {name!r} is empty; the model would be sent nothing")

    declared, actual = CONTRACT[name], placeholders(text)
    if actual != declared:
        missing = sorted(declared - actual)
        unexpected = sorted(actual - declared)
        detail = ", ".join(
            part
            for part in (
                f"missing {missing}" if missing else "",
                f"unexpected {unexpected}" if unexpected else "",
            )
            if part
        )
        raise PromptError(f"prompt {name!r} does not match its contract: {detail}")
    return text


def render(name: str, **values: object) -> str:
    """Fill a prompt in. Every declared placeholder must be supplied."""
    template = load(name)
    supplied = frozenset(values)
    declared = CONTRACT[name]
    if supplied != declared:
        raise PromptError(f"prompt {name!r} takes {sorted(declared)}, got {sorted(supplied)}")
    return template.format(**values)


@lru_cache(maxsize=1)
def personas() -> dict[str, str]:
    """The simulated member's delivery styles, one Markdown file each.

    Adding a persona to a graded run is dropping a file in ``prompts/personas/``;
    no code changes, and ``scripts/live_eval.py`` picks it up by name.
    """
    found = {
        path.stem: path.read_text(encoding="utf-8").strip() for path in sorted(PERSONA_DIR.glob(f"*{SUFFIX}"))
    }
    empty = sorted(name for name, text in found.items() if not text)
    if empty:
        raise PromptError(f"persona file(s) with no instruction: {empty}")
    if not found:
        raise PromptError(f"no personas in {PERSONA_DIR}")
    return found


def validate_all() -> None:
    """Load every declared prompt. Raises PromptError naming the first offender."""
    for name in CONTRACT:
        load(name)
    personas()
