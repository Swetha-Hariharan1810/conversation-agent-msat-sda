"""Conversation guards — the things a live call does that the script doesn't.

Each guard inspects the member's turn *before* any slot logic runs and can end
the turn early. They are deliberately conservative: a guard that fires wrongly
derails the call, so ambiguous turns fall through to the normal path.

One guard is not conservative, and that is on purpose. ``safeguarding`` fires
ahead of everything else in the call, including the request to stop calling, and
it errs towards firing. Every other guard trades a false positive against a lost
survey answer. This one trades it against a member who told an automated caller
they were in trouble and got asked how helpful the website was.

These run on the raw turn, before any model call, so they work offline and they
work when the provider is down. The extractor carries the same two safety
signals for the cases wording alone cannot catch — see ``llm/schema.py``.
"""

from __future__ import annotations

import re

from ..state import SurveyState

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
    r"|i can'?t breathe|chest pain|i'?ve fallen|i have fallen|call an ambulance"
    r")",
    re.I,
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
    re.I,
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
    r"|(?:is |am )?not available to take your call"
    r"|unable to take your call"
    r"|please try (?:your call )?again later)",
    re.I,
)

# The member wants the calls to stop. This is not an unclear answer and must
# never be re-asked; it ends the call and is reported so the list can be updated.
_DO_NOT_CALL = re.compile(
    r"(?:take me off (?:your|the) (?:list|calling list)"
    r"|remove me from (?:your|the) (?:list|calling list|database)"
    r"|do ?n[o']?t call (?:me )?(?:again|any ?more|back)?"
    r"|stop calling (?:me|here)?"
    r"|no more calls"
    r"|do not call list"
    r"|unsubscribe)",
    re.I,
)

# The member stepping away. We wait rather than talking into an empty room.
_HOLD = re.compile(
    r"(?:hold on|hang on|one (?:moment|second|sec|minute)|just a (?:moment|second|sec|minute|tick)"
    r"|give me a (?:moment|second|sec|minute)|let me (?:get|grab|find|put|fetch)|bear with me"
    r"|(?:i'?ll be |be )right back|wait a (?:moment|second|minute))",
    re.I,
)

_HOLDS_KEY = "__holds__"

# Guard outcomes the agent turns into a planned action, so the wording comes
# from the spec and the turn is recorded like any other.
SAFEGUARDING = "safeguarding"
REPRESENTATIVE_REQUEST = "representative_request"
VOICEMAIL = "voicemail"
HOLD = "hold"
HOLD_EXHAUSTED = "hold_exhausted"
DO_NOT_CALL = "do_not_call"


class GuardOutcome:
    """What a guard decided. ``handled`` means the caller must return now."""

    __slots__ = ("handled", "update", "kind")

    def __init__(self, handled: bool = False, update: dict | None = None, kind: str = ""):
        self.handled = handled
        self.update = update or {}
        self.kind = kind


class ConversationGuardsMixin:
    """Adds safety, transfer, voicemail and hold handling to the base agent."""

    def check_guards(self, state: SurveyState, member_text: str) -> GuardOutcome:
        text = member_text or ""
        if not text.strip():
            return GuardOutcome()

        # Ahead of everything, including the request to stop calling: somebody
        # saying both "stop calling me" and "I can't go on" needs a person, not
        # a tidy disposition.
        if _SAFEGUARDING.search(text):
            return GuardOutcome(False, {}, SAFEGUARDING)

        # Asking for a human outranks the survey and the do-not-call guard. A
        # member who says "just put me through to a person, stop calling me"
        # gets the person.
        if _REPRESENTATIVE_REQUEST.search(text):
            return GuardOutcome(False, {}, REPRESENTATIVE_REQUEST)

        if _VOICEMAIL.search(text):
            return GuardOutcome(False, {}, VOICEMAIL)

        if _DO_NOT_CALL.search(text):
            return GuardOutcome(True, {}, DO_NOT_CALL)

        if _HOLD.search(text):
            holds = int((state.get("ambiguous_counts") or {}).get(_HOLDS_KEY, 0)) + 1
            counts = {**(state.get("ambiguous_counts") or {}), _HOLDS_KEY: holds}
            if holds > self.spec.policy.max_consecutive_holds:
                return GuardOutcome(True, {"ambiguous_counts": counts}, HOLD_EXHAUSTED)
            # Reported, not handled: the agent turns it into a planned action so
            # the acknowledgement is spoken in its own words rather than the
            # same sentence every time.
            return GuardOutcome(False, {"ambiguous_counts": counts}, HOLD)

        return GuardOutcome()

    @staticmethod
    def clear_hold_counter(state: SurveyState) -> dict[str, int]:
        counts = dict(state.get("ambiguous_counts") or {})
        counts.pop(_HOLDS_KEY, None)
        return counts
