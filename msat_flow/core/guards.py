"""Conversation guards — the things a live call does that the script doesn't.

Each guard inspects the member's turn *before* any slot logic runs and can end
the turn early. They are deliberately conservative: a guard that fires wrongly
derails the call, so ambiguous turns fall through to the normal path.

One guard is not conservative, and that is on purpose. ``safeguarding`` fires
ahead of everything else in the call, including the request to stop calling, and
it errs towards firing. Every other guard trades a false positive against a lost
survey answer. This one trades it against a member who told an automated caller
they were in trouble and got asked how helpful the website was.

## Who decides

The decision is a model's — a single narrow call, made before the turn is read
as an answer, that returns five booleans and no more (``llm/guard_detector.py``).
Wording alone was never going to be enough here: people ask for a person, or say
they are not coping, in more ways than a pattern can hold, and the patterns that
tried had to be written tight enough to miss the oblique ones rather than fire on
"that website was killing me".

The patterns are still here, and they still run. They are the fallback, used
whenever the model's answer cannot be had:

* no client is configured — the offline path, which must stay runnable;
* the provider failed, timed out, or exhausted its retries.

A guard that cannot reach a provider degrades to wording matching. It does not
end the call, and it does not let the turn through unexamined — the difference
between the two paths is how much they notice, never whether anything is checked
at all.

One asymmetry on top of that: a turn the patterns read as *safeguarding* is
treated as safeguarding whatever the model says. Those phrases are plain
statements of harm, and the point of the guard is that nothing gets to talk the
call out of them. Every other kind is the model's to decide.

## What is decided here rather than there

Precedence. The model is asked what the turn *is* and may say several things at
once; the order in which those beat each other is ``_ORDER`` below, in code,
because "asking for a person outranks asking us to stop calling" is a policy
decision and not a judgement about wording.

The extractor carries ``safeguarding_concern`` and ``asks_for_representative``
too — see ``llm/schema.py``. That is a second look at the same turn from the call
that reads it, and it is what catches the two that matter most on a turn where
this guard fell back to patterns.
"""

from __future__ import annotations

import re

from ..llm.guard_detector import GuardAssessment, detect
from ..state import SurveyState

# ── the fallback patterns ────────────────────────────────────────────────
#
# What runs when the model cannot be reached. Everything below is unchanged from
# when it was the whole of guard detection, including the reasoning behind how
# tightly each one is drawn — a fallback that fires on figures of speech would be
# worse than no fallback, because it fires precisely when nothing else is
# watching.

# ── safety ───────────────────────────────────────────────────────────────

# Harm to the member, by themselves or by somebody else, and the medical
# emergencies an aging-in-place population actually has on the phone. Phrases
# are matched, not keywords: "killing" alone would fire on "that website was
# killing me", and a survey that hands off on a figure of speech will be turned
# off by the people running it.
_SAFEGUARDING = re.compile(
    r"(?:"
    # self-harm and suicidal ideation
    r"kill(?:ing)? myself|end(?:ing)? my (?:own )?life|take (?:my|her|his) own life"
    r"|want(?:ed)? to die|wish(?:ed)? i (?:was|were) dead|better off dead"
    r"|don'?t want to (?:live|be here|go on|wake up|carry on)"
    r"|(?:rather|would rather|honestly rather) not wake up"
    # "I can't go on" errs towards firing: a member who meant the survey rather
    # than their life gets a person on the call, which is recoverable. The other
    # way round is not.
    r"|can'?t (?:go on|carry on|cope)|can'?t take (?:this|it) any ?more"
    r"|no (?:point|reason) (?:in |to )?(?:living|going on|carrying on)"
    r"|hurt(?:ing)? myself|harm(?:ing)? myself|self[- ]harm"
    # harm, neglect or abuse by another person
    r"|(?:i'?m|i am|i'?ve been|i have been) being (?:abused|mistreated|neglected|threatened|hurt)"
    r"|elder abuse|(?:my|the) (?:carer|caregiver|son|daughter|neighbou?r|husband|wife|landlord)"
    r" (?:hits?|hit|hurts?|hurt|threatens?|threatened|shouts? at|locks? me|took my money|steals?)"
    r"|(?:i'?m|i am) (?:not safe|afraid of|frightened of|scared of) (?:him|her|them|my)"
    # medical emergency in progress
    r"|i can'?t breathe|can'?t (?:seem to )?get (?:my|his|her|their) breath"
    r"|chest pain|i'?ve fallen|i have fallen|call an ambulance"
    r"|come over (?:all )?(?:funny|ill|faint|poorly)"
    r")",
    re.IGNORECASE,
)

# The member asking for a human. Every alternative needs an explicit request —
# "can I", "put me through", "give me a person" — because the bare act of
# mentioning a person is not one. Question 5 asks whether the program's staff
# were helpful, so "yes, I could always talk to someone" is an *answer*, and a
# pattern loose enough to catch it would transfer the most cooperative calls on
# the survey's second-to-last question.
#
# It is deliberately conservative for the same reason it can afford to be: the
# extractor carries `asks_for_representative` for everything phrased less
# plainly than this.
_REPRESENTATIVE_REQUEST = re.compile(
    r"(?:"
    r"(?:can|could|may) i (?:please )?(?:speak|talk) (?:to|with)"
    r"|(?:can|could) i (?:have|get) (?:a |an )?(?:real |live )?(?:person|human|representative|rep|agent)\b"
    r"|i (?:want|need) to (?:speak|talk) (?:to|with)"
    r"|i(?:'d| would) (?:like|prefer) to (?:speak|talk) (?:to|with)"
    r"|i(?:'d| would) rather (?:speak|talk) (?:to|with)"
    r"|let me (?:speak|talk) (?:to|with)"
    r"|(?:put|transfer|connect|pass) me (?:through |over )?(?:to|onto|with)"
    r"|(?:get|give) me (?:a |an )?(?:real |live )?(?:person|human|representative|rep|agent)\b"
    r"|(?:speak|talk) (?:to|with) (?:a |an )?(?:real|actual|live|human)"
    r" (?:person|human|being|representative|agent)"
    r"|is there (?:a |an )?(?:real )?(?:person|human|someone|somebody) i (?:can|could)"
    r")",
    re.IGNORECASE,
)

# ── the rest ─────────────────────────────────────────────────────────────

# An answering machine or voicemail greeting. Each alternative is a phrase a
# machine says and a person does not; a bare "you've reached ..." is left out
# deliberately, because people answer their phones that way too.
_VOICEMAIL = re.compile(
    r"(?:leave (?:a|your) (?:message|name and number)"
    r"|after the (?:tone|beep)"
    r"|at the (?:tone|beep)"
    r"|record your message"
    r"|(?:reached|this is) the voice ?mail"
    r"|voice ?mail (?:box|of|system)"
    r"|(?:forwarded|transferred) to voice ?mail"
    r"|(?:is |am )?not available to take your call"
    r"|unable to take your call"
    r"|please try (?:your call )?again later)",
    re.IGNORECASE,
)

# Subset of _VOICEMAIL that only a machine ever says. These override the model.
# Availability phrases ("not available to take your call") are excluded because
# a household member can say them; the model resolves that ambiguity.
_VOICEMAIL_MACHINE = re.compile(
    r"(?:after the (?:tone|beep)"
    r"|at the (?:tone|beep)"
    r"|record your message"
    r"|(?:reached|this is) the voice ?mail"
    r"|voice ?mail (?:box|of|system)"
    r"|(?:forwarded|transferred) to voice ?mail)",
    re.IGNORECASE,
)

# The member wants the calls to stop. This is not an unclear answer and must
# never be re-asked; it ends the call and is reported so the list can be updated.
_DO_NOT_CALL = re.compile(
    r"(?:take me off (?:your|the) (?:list|calling list)"
    r"|remove me from (?:your|the) (?:list|calling list|database)"
    r"|do ?n[o']?t call (?:me )?(?:again|any ?more|back)?"
    r"|do ?n[o']?t ring (?:this number |me )?(?:again|any ?more)?"
    r"|stop calling (?:me|here)?"
    r"|stop ringing (?:me|here)?"
    r"|no more calls"
    r"|do not call list"
    r"|unsubscribe)",
    re.IGNORECASE,
)

# The member stepping away. We wait rather than talking into an empty room.
_HOLD = re.compile(
    r"(?:hold on|hang on|one (?:moment|second|sec|minute)|just a (?:moment|second|sec|minute|tick)"
    r"|give me a (?:moment|second|sec|minute)|let me (?:get|grab|find|put|fetch)|bear with me"
    r"|(?:i'?ll be |be )right back|wait a (?:moment|second|minute))",
    re.IGNORECASE,
)

_HOLDS_KEY = "__holds__"

# Broad vocabulary pre-screen used to skip the guard LLM call on clearly-safe turns.
# Errs heavily toward inclusion for safeguarding words; a false positive just means
# the LLM is called when it wasn't needed — the safe direction to be wrong.
_GUARD_SIGNAL = re.compile(
    r"(?:"
    # Safeguarding-adjacent vocabulary — errs toward inclusion; a false positive
    # just means the LLM is called unnecessarily, but a false negative misses harm.
    r"\b(?:hurt|harm|die|dead|dying|kill|safe|afraid|scared|frighten|abuse|"
    r"cope|breathe|breath|fell|fallen|chest|ambulance|"
    r"can.?t\s+(?:go\s+on|carry\s+on|take\s+it|cope|breathe)|"
    r"no\s+(?:point|reason)\s+(?:in|to)|nothing\s+(?:left|matters|feels)|"
    r"not\s+much\s+left|sit\s+here\s+(?:most|all)\s+days|"
    r"rather\s+not\s+wake\s+up|come\s+over\s+(?:all\s+)?(?:funny|ill|faint|poorly)|"
    r"get\s+(?:my|his|her|their)\s+breath|"
    r"takes?\s+(?:my|her|his)\s+(?:pension|benefits?|money|card|savings)|"
    r"pension\s+card|shouts?\s+at\s+me|"
    r"worth\s+(?:living|going\s+on|carrying\s+on))\b"
    r"|"
    # Representative request signals — includes indirect phrasings needing the LLM
    r"\b(?:speak\s+to|talk\s+to|put\s+me\s+through|transfer\s+me|representative|"
    r"real\s+(?:person|human)|live\s+(?:person|agent)|speak\s+with|talk\s+with|"
    r"proper\s+conversation|chance\s+of\s+(?:having|speaking|talking)|"
    r"conversation\s+with\s+somebody)\b"
    r"|"
    # Hold signals — includes oblique British idioms
    r"\b(?:hold\s+on|hang\s+on|bear\s+with\s+me|one\s+(?:moment|second|sec|minute)|"
    r"just\s+a\s+(?:moment|second|sec)|give\s+me\s+a\s+(?:moment|second)|"
    r"i.?ll\s+be\s+right\s+back|two\s+ticks|kettle)\b"
    r"|"
    # DNC signals
    r"\b(?:take\s+me\s+off|remove\s+me\s+from|stop\s+calling|stop\s+ringing|don.t\s+call\s+me|don.t\s+ring|"
    r"no\s+more\s+calls|unsubscribe|off\s+(?:your|the)\s+list)\b"
    r"|"
    # Voicemail signals
    r"\b(?:voicemail|voice\s+mail|leave\s+a\s+message|after\s+the\s+(?:tone|beep)|"
    r"at\s+the\s+(?:tone|beep)|record\s+your\s+message)\b"
    r")",
    re.IGNORECASE,
)

# Guard outcomes the agent turns into a planned action, so the wording comes
# from the spec and the turn is recorded like any other.
SAFEGUARDING = "safeguarding"
REPRESENTATIVE_REQUEST = "representative_request"
VOICEMAIL = "voicemail"
HOLD = "hold"
HOLD_EXHAUSTED = "hold_exhausted"
DO_NOT_CALL = "do_not_call"
# Member explicitly asked to end the survey mid-call (EventType.CLOSING).
MEMBER_CLOSING = "member_closing"

# Precedence, most urgent first, and the two ways of spotting each one. Both the
# model's answer and the patterns are resolved through this single order, so
# there is one place to read what beats what:
#
# * safety first, ahead even of the request to stop calling — somebody saying
#   both "stop calling me" and "I can't go on" needs a person, not a tidy
#   disposition;
# * then the request for a human, which outranks do-not-call for the same reason:
#   "just put me through to a person, stop calling me" gets the person;
# * voicemail before do-not-call, because a recording cannot consent to anything,
#   including being taken off the list;
# * hold last. It is the only one that is not about ending or diverting the call.
_ORDER: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    (SAFEGUARDING, "safeguarding_concern", _SAFEGUARDING),
    (REPRESENTATIVE_REQUEST, "asks_for_representative", _REPRESENTATIVE_REQUEST),
    (VOICEMAIL, "voicemail_greeting", _VOICEMAIL),
    (DO_NOT_CALL, "asks_not_to_be_called", _DO_NOT_CALL),
    (HOLD, "asks_to_hold", _HOLD),
)


def match_patterns(text: str) -> str:
    """The guard this turn's *wording* trips, or "" — the fallback detector."""
    for kind, _, pattern in _ORDER:
        if pattern.search(text):
            return kind
    return ""


def resolve(assessment: GuardAssessment) -> str:
    """The guard the model's answer amounts to, most urgent field first."""
    for kind, field, _ in _ORDER:
        if getattr(assessment, field, False):
            return kind
    return ""


class GuardOutcome:
    """What a guard decided. ``handled`` means the caller must return now."""

    __slots__ = ("handled", "kind", "update")

    def __init__(
        self, handled: bool = False, update: dict | None = None, kind: str = ""
    ):
        self.handled = handled
        self.update = update or {}
        self.kind = kind


class ConversationGuardsMixin:
    """Adds safety, transfer, voicemail and hold handling to the base agent."""

    async def check_guards(
        self, state: SurveyState, member_text: str, last_agent_message: str = ""
    ) -> GuardOutcome:
        text = member_text or ""
        if not text.strip():
            return GuardOutcome()
        return self._guard_outcome(
            state, await self.detect_guard(text, last_agent_message)
        )

    async def detect_guard(self, text: str, last_agent_message: str = "") -> str:
        """Which guard this turn trips, by model where possible and wording where not.

        The patterns are matched either way. They cost nothing next to a provider
        call, and matching them first means the fallback is already in hand when
        the call fails — there is no second code path to get wrong in the one
        situation where the call is failing.
        """
        matched = match_patterns(text)
        client = getattr(self, "client", None)
        if client is None:
            return matched
        # Skip the LLM call when no guard-adjacent vocabulary is present at all.
        # Normal survey answers (ratings, yes/no, short feedback) never trigger guards;
        # calling the model for them wastes ~0.6-0.8 s every turn with no upside.
        if not matched and not _GUARD_SIGNAL.search(text):
            return ""
        try:
            assessment = await detect(
                client, last_agent_message=last_agent_message, member_text=text
            )
        except Exception:  # noqa: BLE001 - provider outage, rate limit past its retries, bad output
            # A guard cannot end the call over a failed provider call the way
            # reading the turn does: the whole point of this one is that it runs
            # even when nothing else can.
            return matched
        # The two places the patterns overrule the model.
        # Safeguarding: a plain statement of harm cannot be argued with.
        # Voicemail: only machine-unambiguous phrases ("after the tone") override;
        #   availability phrases ("not available to take your call") the model resolves.
        if matched == SAFEGUARDING:
            return matched
        if matched == VOICEMAIL and _VOICEMAIL_MACHINE.search(text):
            return matched
        return resolve(assessment)

    def _guard_outcome(self, state: SurveyState, kind: str) -> GuardOutcome:
        """Turn a detected guard into what the caller must do about it.

        Shared by both detectors on purpose. Whether a hold counts against the
        budget, and what happens when it runs out, is call policy — it cannot
        depend on which of the two noticed the member stepping away.
        """
        if kind == HOLD:
            holds = int((state.get("ambiguous_counts") or {}).get(_HOLDS_KEY, 0)) + 1
            counts = {**(state.get("ambiguous_counts") or {}), _HOLDS_KEY: holds}
            if holds > self.spec.policy.max_consecutive_holds:
                return GuardOutcome(True, {"ambiguous_counts": counts}, HOLD_EXHAUSTED)
            # Reported, not handled: the agent turns it into a planned action so
            # the acknowledgement is spoken in its own words rather than the
            # same sentence every time.
            return GuardOutcome(False, {"ambiguous_counts": counts}, HOLD)

        # Handled: the do-not-call guard ends the call itself, with the approved
        # line. Everything else is reported to the planner and spoken from there.
        if kind == DO_NOT_CALL:
            return GuardOutcome(True, {}, DO_NOT_CALL)

        return GuardOutcome(False, {}, kind)

    @staticmethod
    def clear_hold_counter(state: SurveyState) -> dict[str, int]:
        counts = dict(state.get("ambiguous_counts") or {})
        counts.pop(_HOLDS_KEY, None)
        return counts
