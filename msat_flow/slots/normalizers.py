"""Deterministic normalisers, one per slot type.

These run on whatever the extractor pulled out of the member's turn. They tidy
and map only — a normaliser never invents a value and never guesses at an
ambiguous one. Returning ``""`` means "this is not a usable answer", which makes
the caller read the options out again rather than record something wrong.

On a satisfaction survey the cost of guessing is subtle and permanent: a member
who says "it was fine" has not chosen between Somewhat Helpful and Not Very
Helpful, and a number filed under the wrong one is indistinguishable from a real
answer for ever after.
"""

from __future__ import annotations

import re

from ..script.spec import Option, SlotSpec, SlotType

# How a member actually agrees or declines on the phone.
_AFFIRMATIVE = {
    "yes",
    "yeah",
    "yep",
    "yup",
    "sure",
    "certainly",
    "absolutely",
    "definitely",
    "correct",
    "right",
    "ok",
    "okay",
    "please",
    "did",
    "i did",
    "i have",
    "i would",
}
_NEGATIVE = {"no", "nope", "nah", "never", "not", "none", "negative", "didnt", "havent", "wouldnt"}
_AFFIRMATIVE_PHRASES = re.compile(
    r"\b(?:go ahead|of course|that'?s (?:right|correct|fine)|i suppose so|why not|"
    r"happy to|i do|i did|i would|i think so)\b",
    re.I,
)
_NEGATIVE_PHRASES = re.compile(
    r"\b(?:i don'?t think so|not really|not at all|i'?d rather not|another time|"
    r"i didn'?t|i did not|i haven'?t|i have not|i wouldn'?t|i would not)\b",
    re.I,
)

# "No" and "none" are complete answers to the two free-text questions — the
# document says so in the question itself — so they must record as an answer
# rather than fall through as an unusable turn and get asked again.
_NO_FEEDBACK = re.compile(
    r"^(?:no|none|nope|nothing|nothing really|no feedback|not really|nothing comes to mind|"
    r"nothing at all|i'?m good|all good|no thanks?|no thank you)[.!]?$",
    re.I,
)
NO_FEEDBACK_VALUE = "none"

_ORDINALS = {"first": 0, "second": 1, "third": 2, "fourth": 3, "one": 0, "two": 1, "three": 2, "four": 3}
# "Option two", "number 3", "answer four" — a member picking from a list the
# agent has just read aloud. Deliberately tight: a bare "second" inside a longer
# sentence ("I have a second question") must not select anything.
_NUMBERED_CHOICE = re.compile(r"\b(?:option|number|answer|choice)\s+(one|two|three|four|1|2|3|4)\b", re.I)
_BARE_ORDINAL = re.compile(r"^(?:the\s+)?(first|second|third|fourth|last)(?:\s+one)?[.!]?$", re.I)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", (text or "").lower())


def _flatten(text: str) -> str:
    """Lowercase, punctuation-free, single-spaced, with sentinel spaces.

    Sentinels let a phrase be matched on word boundaries with a plain ``in``,
    so "helpful" never matches inside "unhelpful".
    """
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    collapsed = re.sub(r"\s+", " ", cleaned).strip()
    return " " + collapsed + " "


def normalize_yes_no(text: str) -> str:
    """Map a spoken reply to "yes" or "no", or "" when it is neither."""
    if not (text or "").strip():
        return ""
    if _NEGATIVE_PHRASES.search(text):
        return "no"
    if _AFFIRMATIVE_PHRASES.search(text):
        return "yes"
    words = _words(text)
    if not words:
        return ""
    # A leading negation dominates: "no, I never got round to the website" is a
    # no however many positive-sounding words follow it.
    for word in words[:3]:
        if word in _NEGATIVE:
            return "no"
        if word in _AFFIRMATIVE:
            return "yes"
    if any(word in _NEGATIVE for word in words):
        return "no"
    if any(word in _AFFIRMATIVE for word in words):
        return "yes"
    return ""


def normalize_choice(text: str, options: tuple[Option, ...]) -> str:
    """Map a spoken reply onto one of the declared options, or "".

    Longest match wins, which is what keeps "not very helpful" from being read
    as "very helpful". A tie between two *different* options is treated as no
    answer at all rather than resolved arbitrarily.
    """
    haystack = _flatten(text)
    if haystack.strip() and options:
        best_value, best_len, tied = "", 0, False
        for option in options:
            for phrase in option.phrases:
                needle = _flatten(phrase)
                if len(needle) < 3 or needle not in haystack:
                    continue
                if len(needle) > best_len:
                    best_value, best_len, tied = option.value, len(needle), False
                elif len(needle) == best_len and option.value != best_value:
                    tied = True
        if best_value and not tied:
            return best_value

    return _numbered_choice(text, options)


def _numbered_choice(text: str, options: tuple[Option, ...]) -> str:
    """ "Option two", "the third one" — picking by position from a read-out list."""
    stripped = (text or "").strip()
    match = _NUMBERED_CHOICE.search(stripped) or _BARE_ORDINAL.match(stripped)
    if not match:
        return ""
    token = match.group(1).lower()
    index = (
        len(options) - 1
        if token == "last"
        else _ORDINALS.get(token, int(token) - 1 if token.isdigit() else -1)
    )
    return options[index].value if 0 <= index < len(options) else ""


def normalize_feedback_text(text: str) -> str:
    """Keep the member's own words. "No" and "none" record as ``none``."""
    collapsed = re.sub(r"\s+", " ", (text or "").strip())
    if not collapsed:
        return ""
    if _NO_FEEDBACK.match(collapsed):
        return NO_FEEDBACK_VALUE
    return collapsed


def normalize_person_name(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z'\- ]", " ", text or "")
    parts = [part.capitalize() for part in cleaned.split() if part]
    return " ".join(parts) if parts else ""


def normalize(declared: SlotSpec, text: str) -> str:
    """Normalise ``text`` for ``declared``.

    Dispatch takes the whole slot spec rather than just its type because a choice
    slot cannot be normalised without the options it is choosing between — and
    those come from the document, not from a table in here.
    """
    if declared.type is SlotType.YES_NO:
        return normalize_yes_no(text)
    if declared.type is SlotType.CHOICE:
        return normalize_choice(text, declared.options)
    if declared.type is SlotType.FEEDBACK_TEXT:
        return normalize_feedback_text(text)
    if declared.type is SlotType.PERSON_NAME:
        return normalize_person_name(text)
    raise ValueError(f"no normaliser for slot type {declared.type!r}")  # pragma: no cover
