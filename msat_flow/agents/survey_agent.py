"""MsatSurveyAgent — the outbound member-satisfaction caller.

One turn of this agent is: read what the member said, record whatever it
contained, then let the planner decide the next move from what is still
outstanding. There is no script pointer and no keyword routing, so a member is
free to answer two questions at once, take a question as a cue to tell a story,
or correct an answer four questions later.

The survey-specific judgement lives in two places, and both are deliberate:

* **A question the member will not answer is recorded as declined, and the call
  goes on.** There is no escalation path for it. Handing a satisfaction call to a
  human because somebody would rather not rate the staff serves nobody, and the
  gap is reported honestly instead.
* **The gates latch only where they were asked.** Identity and consent are read
  from the turn that put them and no other, so a "yes" meaning "yes, speaking"
  can never be recorded as consent to be surveyed. The cost is that a member who
  volunteers both at once is asked anyway; that is much cheaper than surveying
  someone who never agreed to it.
"""

from __future__ import annotations

import asyncio
import re

from ..core import guards
from ..core.agent import BaseAgent
from ..core.guards import GuardOutcome
from ..core.pending_intents import ACK_ONLY_KINDS, open_intents, unfinished
from ..llm.extractor import extract
from ..llm.response_generator import generate
from ..llm.schema import EventType, IdentityDetail, TurnDecision
from ..planner import (
    CONSENT_DECLINED,
    CONSENT_GRANTED,
    FINAL_ACTIONS,
    IDENTITY_CONFIRMED,
    IDENTITY_UNAVAILABLE,
    IDENTITY_WRONG_NUMBER,
    PRESERVE_AWAITING,
    QUESTION_ACTIONS,
    TRANSFER_ACTIONS,
    Action,
    Plan,
    applies,
    outstanding_questions,
    plan_next,
    skipped_questions,
)
from ..script.spec import SurveySpec, load_spec
from ..state import SurveyState

# Phase is reporting only — the planner never reads it. It exists so a call can
# be monitored and so the outcome says where it got to.
_ACTION_PHASE = {
    Action.HANDOFF_SAFEGUARDING: "closing",
    Action.HANDOFF_REPRESENTATIVE: "closing",
    Action.HANDOFF_HOLD_LIMIT: "closing",
    Action.LEAVE_VOICEMAIL: "opening",
    Action.ACKNOWLEDGE_HOLD: "survey",
    Action.GREET: "identity",
    Action.END_UNAVAILABLE: "closing",
    Action.END_WRONG_NUMBER: "closing",
    Action.ASK_CONSENT: "consent",
    Action.OFFER_RESCHEDULE: "consent",
    Action.TRANSFER_RESCHEDULE: "closing",
    Action.ASK_RESCHEDULE_DATETIME: "consent",
    Action.CLOSE_RESCHEDULE: "closing",
    Action.END_UNINTERESTED: "closing",
    Action.ASK: "survey",
    Action.CLOSE: "closing",
}

# How each ending is reported. Every way the call can stop has one, so a batch of
# results never contains a silent blank.
_ACTION_DISPOSITION = {
    Action.HANDOFF_SAFEGUARDING: "safeguarding_handoff",
    Action.HANDOFF_REPRESENTATIVE: "representative_requested",
    Action.HANDOFF_HOLD_LIMIT: "hold_limit_transfer",
    Action.LEAVE_VOICEMAIL: "voicemail_left",
    Action.END_UNAVAILABLE: "policyholder_unavailable",
    Action.END_WRONG_NUMBER: "wrong_number",
    Action.TRANSFER_RESCHEDULE: "reschedule_requested",
    Action.CLOSE_RESCHEDULE: "reschedule_requested",
    Action.END_UNINTERESTED: "uninterested",
}

# Why the call was handed to a human, for the transfer event a human reads.
_TRANSFER_REASON = {
    Action.HANDOFF_SAFEGUARDING: "member_may_be_at_risk",
    Action.HANDOFF_REPRESENTATIVE: "member_asked_for_a_representative",
    Action.HANDOFF_HOLD_LIMIT: "hold_limit_reached",
    Action.TRANSFER_RESCHEDULE: "member_requested_reschedule",
}

# Date/time patterns a member would say when they can actually name a time.
_DATETIME_RE = re.compile(
    r"\b(?:"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"today|tomorrow|tonight|"
    r"morning|afternoon|evening|night|noon|midnight|"
    r"next\s+(?:week|month|monday|tuesday|wednesday|thursday|friday|saturday|sunday)|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"\d+\s*(?:am|pm|o'clock)|"
    r"(?:at|after|around|by|before)\s+\d+|"
    r"in\s+(?:a\s+|an?\s+)?(?:hour|minute|day|week|couple)"
    r")\b",
    re.IGNORECASE,
)

# Negation words that, when appearing just before a datetime term, indicate
# the member is rejecting that time rather than offering it.
_NEGATION_RE = re.compile(
    r"\b(?:can'?t|cannot|can\s+not|won'?t|will\s+not|not|don'?t|do\s+not|"
    r"doesn'?t|does\s+not|never|unable|unavailable)\b",
    re.IGNORECASE,
)
_NEGATION_WINDOW = 40  # characters to look back before a datetime match


def _has_datetime_content(text: str) -> bool:
    """True if text contains a datetime reference the member is offering, not rejecting."""
    if not text:
        return False
    for m in _DATETIME_RE.finditer(text):
        window = text[max(0, m.start() - _NEGATION_WINDOW) : m.start()]
        if not _NEGATION_RE.search(window):
            return True
    return False


_DO_NOT_CALL = "do_not_call"
_ENDED_EARLY = "ended_early"
_SURVEYED = "surveyed"
_PARTIAL = "partially_surveyed"

# Guard outcomes the planner turns into a spoken action, rather than the guard
# speaking for itself. Keeping the wording on that side is what lets the pause
# acknowledgement be said in the agent's own words while the two handoffs stay
# exactly as approved.
_PLANNED_GUARDS = frozenset(
    {guards.SAFEGUARDING, guards.REPRESENTATIVE_REQUEST, guards.VOICEMAIL, guards.HOLD}
)


def _last_message(messages: list, role: str) -> str:
    wanted = {"user": {"user", "human"}, "assistant": {"assistant", "ai"}}.get(
        role, {role}
    )
    for message in reversed(messages or []):
        kind = (
            message.get("role")
            if isinstance(message, dict)
            else getattr(message, "type", "")
        )
        if kind in wanted:
            content = (
                message.get("content", "")
                if isinstance(message, dict)
                else getattr(message, "content", "")
            )
            if content:
                return str(content)
    return ""


class MsatSurveyAgent(BaseAgent):
    AGENT_NAME = "msat_survey_agent"

    def __init__(self, client=None, spec: SurveySpec | None = None):
        super().__init__()
        self.client = client
        self.spec = spec or load_spec()

    # ── the three gates ──────────────────────────────────────────────────

    @property
    def _identity_slot(self) -> str:
        return self.spec.of_kind("intro").slot

    @property
    def _consent_slot(self) -> str:
        return self.spec.of_kind("consent").slot

    @property
    def _reschedule_slot(self) -> str:
        return self.spec.of_kind("reschedule_offer").slot

    @property
    def _gate_slots(self) -> frozenset[str]:
        return frozenset(
            {self._identity_slot, self._consent_slot, self._reschedule_slot}
        )

    def _gate_limit(self, slot: str) -> int:
        policy = self.spec.policy
        if slot == self._identity_slot:
            return policy.max_identity_asks
        if slot in (self._consent_slot, self._reschedule_slot):
            return policy.max_consent_asks
        return policy.max_asks_per_slot

    @staticmethod
    def _field_event(field: str, value: str) -> dict:
        return {"eventType": "CallAgentField", "data": {"field": field, "value": value}}

    # ── turn ─────────────────────────────────────────────────────────────

    async def run(self, state: SurveyState) -> dict:
        member_text = _last_message(state.get("messages", []), "user")
        last_agent = _last_message(state.get("messages", []), "assistant")

        # First turn of the call: nothing to read, just open.
        if not member_text:
            return await self._act(state, self._plan(state), updates={})

        # Both questions about this turn go out at once — see `_look`. What comes
        # back is the guard's answer, what the turn was read as, and whatever
        # reading it raised; the last two are ignored entirely on every path
        # below that the guard settles.
        guard, decision, unread = await self._look(state, member_text, last_agent)
        # Safety, a request for a person, an answering machine and a pause are
        # all turned into planned actions, so their wording comes from the spec
        # and the turn is recorded like any other. Crucially, the first two are
        # decided WITHOUT REFERENCE to the turn as an answer, by a call of their
        # own that is asked nothing but this: a member who is not safe must never
        # have what they said weighed up against question 3 first. The reading
        # runs alongside rather than after, so it costs them no time either — but
        # a turn the guard fires on is never read as survey content, and what the
        # extractor made of it is discarded here unlooked at.
        if guard.kind in _PLANNED_GUARDS:
            return await self._act(
                state, self._plan(state, guard=guard.kind), updates=dict(guard.update)
            )
        if guard.kind == _DO_NOT_CALL:
            return self._end(
                state,
                self.spec.policy.line(_DO_NOT_CALL),
                disposition=_DO_NOT_CALL,
                reason="member asked not to be called again",
            )
        if guard.kind == guards.HOLD_EXHAUSTED:
            plan = self._plan(state, guard=guards.HOLD_EXHAUSTED)
            return await self._act(state, plan, updates=dict(guard.update))
        if guard.handled:
            return {**self.persisted(), **guard.update}

        awaiting = state.get("awaiting_slot", "")
        if unread is not None:  # provider outage, rate limit past its retries
            # Never mistake a failure to READ the turn for the member being
            # unclear: that would burn a retry against someone who answered
            # perfectly. End the call, keep every answer already recorded, and
            # say why.
            #
            # Only reached once the guard has let the turn through. A failure
            # here on a turn that also asked for a person must not end the call
            # over the reading — the member gets the person, and this is not
            # looked at.
            return self._end(
                state,
                self.spec.policy.line("unable_to_continue"),
                disposition=_ENDED_EARLY,
                reason=f"could not process the turn: {unread}",
            )
        # A second look at the same turn, from the call that reads it. The guard
        # above has usually settled these already; what this catches is the turn
        # where the guard's own model call failed and it fell back to wording,
        # which is exactly when an obliquely worded "I don't see much point any
        # more" would otherwise go past. It is why the extractor is asked to lean
        # towards raising a concern rather than away from it.
        if decision.safeguarding_concern:
            return await self._act(
                state, self._plan(state, guard=guards.SAFEGUARDING), updates={}
            )
        if decision.asks_for_representative:
            return await self._act(
                state,
                self._plan(state, guard=guards.REPRESENTATIVE_REQUEST),
                updates={},
            )

        # Member explicitly asked to end the survey — honour it regardless of
        # where in the call this happens; survey_started is only required for the
        # CLOSING event type to avoid false positives on ambiguous goodbyes.
        if decision.refuses_survey:
            return await self._act(
                state,
                self._plan(state, guard=guards.MEMBER_CLOSING),
                updates={},
            )

        # Member asked to be called back at another time. Honour at any turn —
        # consent phase or mid-survey — and skip recording any survey answers
        # from this turn. A datetime they offered in the same breath is captured
        # so the call can close immediately if they named one.
        if decision.wants_reschedule:
            dt = decision.values.pop("reschedule_datetime", None)
            if dt is None and _has_datetime_content(member_text):
                dt = member_text.strip()
            upd: dict = {
                "ambiguous_counts": self.clear_hold_counter(state),
                "consent": CONSENT_DECLINED,
                "reschedule": "yes",
            }
            if dt and not state.get("reschedule_datetime"):
                upd["reschedule_datetime"] = dt
            # Both fields bypass record_many — it only knows spec slots — so their events have to be raised here.
            # A later turn that re-enters this same branch must not re-report a fact already recorded.
            events = (
                [self._field_event("wants_reschedule", "yes")]
                if state.get("reschedule") != "yes"
                else []
            )
            if "reschedule_datetime" in upd:
                events.append(
                    self._field_event("reschedule_datetime", upd["reschedule_datetime"])
                )
            upd["metadata_events"] = events
            return await self._act(
                state,
                self._plan(state, updates=upd),
                updates=upd,
                last_member_message=member_text,
                free_flow=True,
            )

        if decision.event_type is EventType.CLOSING and state.get("survey_started"):
            return await self._act(
                state,
                self._plan(state, guard=guards.MEMBER_CLOSING),
                updates={},
            )

        self.capture_and_triage(decision, slot=awaiting)

        updates: dict = {"ambiguous_counts": self.clear_hold_counter(state)}

        # reschedule_datetime is a state field, not a spec slot — the slot manager
        # cannot handle it, so intercept it before record_many.
        datetime_from_llm: str | None = decision.values.pop("reschedule_datetime", None)

        # Corrections win over new answers for the same question.
        rejected: dict[str, str] = {}
        corrected_slots: list[str] = []
        for slot, raw in (decision.corrections or {}).items():
            if not self._may_record(slot, awaiting):
                continue
            accepted, reason = self.record(slot, raw)
            if accepted:
                corrected_slots.append(slot)
                self.resolve_intents(target=slot)
            else:
                rejected[slot] = reason

        recordable = {
            slot: raw
            for slot, raw in (decision.values or {}).items()
            if self._may_record(slot, awaiting)
            and slot not in (decision.corrections or {})
            and not (decision.off_topic and slot == awaiting)
            # A gate slot value must not be recorded when the member also declined:
            # the decline wins and _gate_updates must not see a stale answer.
            and not (
                decision.declines_question
                and slot == awaiting
                and slot in self._gate_slots
            )
        }
        newly_answered, more_rejected = self.record_many(recordable)
        rejected.update(more_rejected)
        # A clarification raised on the question just answered is now settled.
        for slot in newly_answered:
            self.resolve_clarifications(slot=slot)

        # Emit one CallAgentField event per field recorded this turn.
        field_events = [
            self._field_event(slot, self.answer(slot))
            for slot in corrected_slots + newly_answered
        ]
        if field_events:
            updates["metadata_events"] = field_events

        # An answer whose gating question has since changed does not belong to
        # this member's survey any more. Dropping it here is what keeps a
        # corrected "actually, I never looked at them" from leaving a
        # helpfulness rating behind on a question that is now skipped.
        self._drop_inapplicable(state)

        updates.update(self._gate_updates(state, decision))

        if (
            awaiting == "reschedule_datetime"
            and member_text.strip()
            and not state.get("reschedule_datetime")
        ):
            ask_count = (state.get("ask_counts") or {}).get("reschedule_datetime", 0)
            at_limit = ask_count >= self._gate_limit("reschedule_datetime")
            # LLM primary: extractor sets the slot only when it recognised a real time reference.
            # Regex fallback: catches valid times the LLM missed (e.g. model quirk on edge cases).
            datetime_value = datetime_from_llm or (
                member_text.strip() if _has_datetime_content(member_text) else None
            )
            if datetime_value or at_limit:
                updates["reschedule_datetime"] = datetime_value or member_text.strip()
                # Another field record_many never sees — same reasoning as the
                # wants_reschedule shortcut above.
                updates["metadata_events"] = updates.get("metadata_events", []) + [
                    self._field_event(
                        "reschedule_datetime", updates["reschedule_datetime"]
                    )
                ]
            else:
                plan = self._plan(
                    state, updates=updates, declined=list(state.get("declined") or [])
                )
                return await self._act(
                    state,
                    plan,
                    updates=updates,
                    last_member_message=member_text,
                    retry_slot="reschedule_datetime",
                    retry_reason="no specific date or time was given",
                    free_flow=True,
                )

        # The member would rather not answer what was just asked. That is an
        # answer about the survey, not a failure of the call.
        declined = list(state.get("declined") or [])
        if decision.declines_question or decision.event_type is EventType.DECLINED:  # noqa: SIM102
            if (
                awaiting
                and awaiting not in self._gate_slots
                and awaiting not in declined
            ):
                declined.append(awaiting)
                updates["declined"] = declined

        retry = self._retry_target(awaiting, decision, rejected, declined)
        if retry:
            slot, reason = retry
            over = self.slot(slot).attempt_count >= self._gate_limit(slot)
            if over and slot in self._gate_slots:
                return await self._gate_gave_up(state, slot, updates)
            if over:
                if slot not in declined:
                    declined.append(slot)
                updates["declined"] = declined
                return await self._gate_gave_up(state, slot, updates)

        plan = self._plan(state, updates=updates, declined=declined)

        # Backstop: a question that has been PUT too many times without ever
        # being answered stops going out. The retry counter cannot see this case
        # — the member replies every time, just never to this question.
        ask_counts = dict(state.get("ask_counts") or {})
        for _ in range(len(self.spec.slots) + 1):
            slot = plan.slot
            if plan.action not in QUESTION_ACTIONS or not slot or self.answered(slot):
                break
            if ask_counts.get(slot, 0) < self._gate_limit(slot):
                break
            if slot in self._gate_slots:
                return await self._gate_gave_up(state, slot, updates)
            if slot not in declined:
                declined.append(slot)
            updates["declined"] = declined
            return await self._gate_gave_up(state, slot, updates)

        # Only re-ask if the planner still wants that question. A correction can
        # re-open an earlier branch — answering "actually I never opened them"
        # replaces the helpfulness question with the reason question — and
        # re-asking what we happened to be waiting on would talk over it.
        if retry and plan.slot == retry[0]:
            slot, reason = retry
            return await self._act(
                state,
                plan,
                updates=updates,
                last_member_message=member_text,
                retry_slot=slot,
                retry_reason=reason,
                # retries always need a personalised bridge — free flow unconditionally
                free_flow=True,
            )
        # Suppress the previous member message when moving to a fresh question.
        # Passing it through causes the generator to see e.g. "Yes." while being
        # asked to put a yes/no question, which makes it conclude the question has
        # already been answered and produce only "Thank you." — leaving the slot
        # never asked and the call looping until a guard fires.
        last_msg = (
            ""
            if self.asks_and_nothing_more(plan, decision, ask_counts=ask_counts)
            else member_text
        )
        return await self._act(
            state,
            plan,
            updates=updates,
            last_member_message=last_msg,
            # extractor signals whether the transition needs dynamic generation
            free_flow=decision.requires_free_flow,
        )

    # ── reading the turn ─────────────────────────────────────────────────

    async def _look(
        self, state: SurveyState, member_text: str, last_agent: str
    ) -> tuple[GuardOutcome, TurnDecision | None, BaseException | None]:
        """Ask both questions about this turn at once.

        The guard call and the extraction call are put the same two things — what
        the caller last said and what the member said back — and neither reads
        the other's answer. Asked one after the other, the member waits for the
        sum of them; asked together, they wait for the longer.

        What that buys is time and nothing else. The guard still decides the turn
        by itself, and every path it settles throws the reading away unlooked at,
        exactly as it did when the reading had not been started yet.

        Returns the guard's outcome, what the turn was read as, and whatever
        reading it raised — never both of the last two.
        """
        # Settled before anything is launched, so the concurrent path only ever
        # starts a call that would have been made anyway.
        settled = self._read_without_a_call(state, member_text)
        if settled is not None:
            return (
                await self.check_guards(state, member_text, last_agent),
                settled,
                None,
            )

        guard_task = asyncio.create_task(
            self.check_guards(state, member_text, last_agent)
        )
        read_task = asyncio.create_task(self._read(state, member_text, last_agent))

        # Wait for whichever finishes first rather than always blocking on guard.
        # When extract finishes first (common after the guard pre-screen makes guard
        # instant), we return immediately so generate can start without waiting for
        # guard's LLM round-trip. When guard finishes first we check it; if it fired
        # we cancel extract and return early without waiting for it.
        done, _ = await asyncio.wait(
            {guard_task, read_task}, return_when=asyncio.FIRST_COMPLETED
        )

        if guard_task in done and read_task not in done:
            # Guard resolved first — check it before extract finishes.
            try:
                guard = guard_task.result()
            except BaseException:
                read_task.cancel()
                await asyncio.gather(read_task, return_exceptions=True)
                raise
            if guard.kind:
                read_task.cancel()
                await asyncio.gather(read_task, return_exceptions=True)
                return guard, None, None
            try:
                read = await read_task
            except BaseException as exc:  # noqa: BLE001
                return guard, None, exc
            return guard, read, None

        # Extract finished first (or both finished simultaneously).
        try:
            read = read_task.result()
        except BaseException as read_exc:  # noqa: BLE001
            # Extract failed — still collect guard before returning so the guard
            # path is not silently skipped on a failed-read turn.
            try:
                guard = await guard_task
            except Exception:  # noqa: BLE001
                raise read_exc
            return guard, None, read_exc

        guard = await guard_task
        if guard.kind:
            return guard, None, None
        return guard, read, None

    def _read_without_a_call(
        self, state: SurveyState, member_text: str
    ) -> TurnDecision | None:
        """What the turn reads as when no provider call is needed, or ``None``.

        The only turn that skips the extractor is every turn when no model is
        configured (offline mode). The datetime turn used to be bypassed too, but
        now the extractor validates whether the member actually named a time.
        """
        if self.client is None:
            return self._read_offline(state, member_text)
        return None

    async def _read(
        self, state: SurveyState, member_text: str, last_agent: str
    ) -> TurnDecision:
        """Read the turn with the model. The no-provider cases are settled above."""
        asked = tuple(filter(None, [state.get("awaiting_slot", "")]))
        return await extract(
            self.client,
            self.spec,
            asked_slots=asked,
            last_agent_message=last_agent,
            member_text=member_text,
            progress_summary=self._progress_summary(state),
        )

    @staticmethod
    def _read_offline(state: SurveyState, member_text: str) -> TurnDecision:
        """Read a turn with no model, using the normalisers alone.

        The member's words are offered to the question we are actually waiting
        on, and to nothing else. The normaliser then accepts them or does not —
        so "extremely helpful" lands and "it was alright" does not, exactly as
        on a live call.

        This is deliberately literal. It cannot notice an answer given out of
        turn, a correction, or a question asked back, so an offline call walks
        the script in order and nothing more. It exists so the flow can be
        driven end to end without a provider, not to stand in for one.
        """
        awaiting = state.get("awaiting_slot") or ""
        if not awaiting or not (member_text or "").strip():
            return TurnDecision()
        return TurnDecision(values={awaiting: member_text})

    def _may_record(self, slot: str, awaiting: str) -> bool:
        """Whether this turn is allowed to settle ``slot``.

        Survey answers may arrive at any point — that is the whole design. The
        three gates may not: they are only read from the turn that asked them,
        so "yes, speaking" cannot become consent and a cheerful "sure" to a
        survey question cannot retroactively grant it.
        """
        return slot not in self._gate_slots or slot == awaiting

    def _gate_updates(self, state: SurveyState, decision: TurnDecision) -> dict:
        """Translate the gate answers into the call's identity/consent state."""
        updates: dict = {}

        identity = state.get("identity") or ""
        if not identity:
            reached = self.answer(self._identity_slot)
            if reached == "yes":
                updates["identity"] = IDENTITY_CONFIRMED
            elif reached == "no" or decision.identity_detail is not IdentityDetail.NONE:
                updates["identity"] = (
                    IDENTITY_WRONG_NUMBER
                    if decision.identity_detail is IdentityDetail.WRONG_NUMBER
                    else IDENTITY_UNAVAILABLE
                )

        if not state.get("consent"):
            awaiting = state.get("awaiting_slot", "")
            # declines_question beats a simultaneously extracted "yes": the member
            # said both "I have a couple of minutes" and "I don't want a survey",
            # and the refusal must win over the partial affirmative.
            if awaiting == self._consent_slot and decision.declines_question:
                updates["consent"] = CONSENT_DECLINED
            else:
                consent = self.answer(self._consent_slot)
                if consent == "yes":
                    updates["consent"] = CONSENT_GRANTED
                elif consent == "no":
                    updates["consent"] = CONSENT_DECLINED

        if not state.get("reschedule"):
            awaiting = state.get("awaiting_slot", "")
            if awaiting == self._reschedule_slot and decision.declines_question:
                updates["reschedule"] = "no"
            else:
                reschedule = self.answer(self._reschedule_slot)
                if reschedule:
                    updates["reschedule"] = reschedule

        return updates

    def _drop_inapplicable(self, state: SurveyState) -> list[str]:
        """Forget answers to questions this member should no longer be asked."""
        dropped: list[str] = []
        for turn in self.spec.questions:
            if turn.when is None or not turn.slot or not self.answered(turn.slot):
                continue
            if not applies(
                turn,
                answers=self._answers,
                payload_lookup=lambda s: self.payload_value(state, s),
            ):
                self.forget(turn.slot)
                dropped.append(turn.slot)
        return dropped

    def _retry_target(
        self,
        awaiting: str,
        decision: TurnDecision,
        rejected: dict[str, str],
        declined: list[str],
    ) -> tuple[str, str] | None:
        """The question we must put again, if any, and why.

        A member who answers our question with a question of their own has not
        failed to answer it, and neither has one who declined — the first gets
        answered and asked again, the second is settled. Only an unusable answer
        or a rejected one counts against the budget.

        The reason travels with the slot into ``speak_line.retry.md``, so it has
        to be true: it is what decides whether the next line apologises for
        mishearing or reads the question out again.
        """
        if not awaiting or self.answered(awaiting) or awaiting in declined:
            return None
        if decision.declines_question:
            # Settled, not retried — including when they declined and asked us
            # something in the same breath. "I'd rather not, and who are you
            # with?" is an answer about the survey; re-asking would talk over it.
            return None
        if awaiting in rejected:
            # What they said was offered to the slot and the slot would not have
            # it. That is a real failed attempt however the turn was labelled,
            # and its reason is more specific than anything below.
            return awaiting, rejected[awaiting]
        if decision.event_type is EventType.ANSWERED_WITH_REQUEST:
            # They asked us something rather than answering — to say it again, or
            # what a word in it meant. The question goes out again WITHOUT
            # charging the attempt: a member who could not hear the question, or
            # did not know what it was asking, has not failed to answer it, and
            # three of those must not add up to a question reported as one they
            # would rather not say.
            #
            # Ahead of the corrections check on purpose. A turn that revises an
            # earlier answer AND asks us something still needs the next line to
            # deal with what was asked, and this branch spends nothing either
            # way. If the correction re-opened a different branch, `run` drops
            # the retry anyway — it only applies one the planner still wants.
            return awaiting, "they asked us something back rather than answering"
        if decision.corrections:
            # They revised an earlier answer instead of answering this one. That
            # is a contribution, not a failure to answer, and charging it to the
            # outstanding question would spend the budget on someone being
            # careful.
            return None
        if decision.off_topic:
            self.slot(awaiting).record(None, success=False)
            return awaiting, "the response was unrelated to the survey question"
        if decision.event_type in (EventType.AMBIGUOUS, EventType.CORRECTED):
            self.slot(awaiting).record(None, success=False)
            return awaiting, "the answer was unclear"
        if decision.event_type is EventType.ANSWERED and not decision.values:
            self.slot(awaiting).record(None, success=False)
            return awaiting, "no answer was given"
        return None

    # ── planning and acting ──────────────────────────────────────────────

    def _progress_summary(self, state: SurveyState, updates: dict | None = None) -> str:
        """Compact snapshot of recorded answers and gate state for the LLM prompt."""
        merged = {**state, **(updates or {})}
        parts: list[str] = []
        if self._answers:
            lines = "\n".join(
                f"  - {slot}: {val}" for slot, val in self._answers.items()
            )
            parts.append(f"Answers recorded:\n{lines}")
        declined = list(merged.get("declined") or [])
        if declined:
            parts.append(f"Declined to answer: {', '.join(declined)}")
        gates = [
            f"{key}={merged[key]}" for key in ("identity", "consent") if merged.get(key)
        ]
        if gates:
            parts.append(", ".join(gates))
        return "\n".join(parts)

    def _plan(
        self,
        state: SurveyState,
        *,
        updates: dict | None = None,
        declined: list[str] | None = None,
        guard: str = "",
    ) -> Plan:
        merged = {**state, **(updates or {})}
        return plan_next(
            self.spec,
            answers=dict(self._answers),
            declined=tuple(
                declined if declined is not None else merged.get("declined") or ()
            ),
            identity=merged.get("identity") or "",
            consent=merged.get("consent") or "",
            reschedule=merged.get("reschedule") or "",
            reschedule_datetime=merged.get("reschedule_datetime") or "",
            survey_started=bool(merged.get("survey_started")),
            guard=guard,
            payload_lookup=lambda slot: self.payload_value(state, slot),
        )

    async def _gate_gave_up(self, state: SurveyState, slot: str, updates: dict) -> dict:
        """A gate we asked as often as policy allows and never got an answer to."""
        plan = self._plan(state, guard=guards.REPRESENTATIVE_REQUEST, updates=updates)
        return await self._act(state, plan, updates=updates)

    def asks_and_nothing_more(
        self,
        plan: Plan,
        decision: TurnDecision | None,
        *,
        ask_counts: dict[str, int],
        retry_slot: str = "",
    ) -> bool:
        """Whether this turn's line is the question and nothing else.

        True only for a turn that puts a question the member has never been asked
        before, in answer to a turn that held nothing but an answer. There is
        nothing to acknowledge, nothing to re-read, nothing to pick back up — the
        line the generator would compose is the question, so a fixed line would
        say the same thing.

        Every other turn is asking the generator to *bridge*: to thank somebody
        for a long answer, to read the options out again after an unclear one, to
        come back to the question a pause interrupted, or to acknowledge
        something raised that this call cannot act on. That is the whole reason
        it is there.

        Pure: no model, no I/O, and — the one worth stating outright — no
        mutation. It reads the intent ledger through ``open_intents``, never
        through ``side_request_ack``, which marks intents acknowledged as it
        answers. A predicate that quietly acknowledged an intent would leave the
        member's remark marked as spoken to on a turn where nothing was said
        about it.

        Two of the checks look like one and are not:

        * ``secondary_intents`` is what the member raised in this turn.
        * ``open_intents(..., kinds=ACK_ONLY_KINDS)`` is what is still owed a
          line, and it covers ``UNSUPPORTED`` and nothing else — there is one
          acknowledgement to say and it is a sentence about member services.

        Three kinds are neither: ``SIDE_REQUEST``, ``CLARIFICATION`` and
        ``OFF_TOPIC`` all go on the ledger and all leave the ack empty, and an
        ``OFF_TOPIC`` is filed NOTED so it is never open either. Today those
        turns still reach the generator with the member's own words as
        ``last_member_message``, and the agent can answer them — which is why a
        call full of asides and questions about the question sounds right even
        when nothing is said about them explicitly. Collapse the two checks into
        one and those turns get a fixed line instead, and what the member raised
        is dropped in silence.
        """
        if decision is None:
            return False
        # ACKNOWLEDGE_HOLD is not in QUESTION_ACTIONS today. It is named anyway,
        # because it is the one action that says something while leaving the
        # question outstanding (see PRESERVE_AWAITING) — if it ever joins that
        # set, "take your time" must not become a fixed line.
        if (
            plan.action not in QUESTION_ACTIONS
            or plan.action is Action.ACKNOWLEDGE_HOLD
        ):
            return False
        # Asked before means there is a reason it is being asked again, and the
        # member should hear that rather than the same sentence twice.
        if ask_counts.get(plan.slot, 0) != 0 or retry_slot:
            return False
        if decision.event_type is not EventType.ANSWERED:
            return False
        if decision.corrections or decision.secondary_intents:
            return False
        return not open_intents(self._pending_intents, kinds=ACK_ONLY_KINDS)

    async def _act(
        self,
        state: SurveyState,
        plan: Plan,
        *,
        updates: dict,
        last_member_message: str = "",
        retry_slot: str = "",
        retry_reason: str = "",
        free_flow: bool = True,
    ) -> dict:
        self.visit(plan.preamble_node)
        self.visit(plan.node)

        message = await generate(
            self.client,
            plan,
            last_member_message=last_member_message,
            ack=self.side_request_ack(),
            retry_slot=retry_slot,
            retry_reason=retry_reason,
            attempt=self.slot(retry_slot).attempt_count if retry_slot else 0,
            attempt_limit=self._gate_limit(retry_slot)
            if retry_slot
            else self.spec.policy.max_asks_per_slot,
            # Progress context only matters when retrying a slot; on straight-through
            # turns the planner already chose the right question and the extra tokens add latency.
            progress_summary=self._progress_summary(state, updates)
            if retry_slot
            else "",
            free_flow=free_flow,
        )

        # The line just composed puts the question again, which is the answer to
        # a member who asked what it meant or asked to hear it once more. Said
        # after the line rather than before it because that is when it is true —
        # and true even when the provider failed, since the fallback reads the
        # script's own wording, options and all.
        if retry_slot:
            self.resolve_clarifications(slot=retry_slot)

        extra: dict = {"phase": _ACTION_PHASE.get(plan.action, "survey")}
        asked = retry_slot or (plan.slot if plan.action in QUESTION_ACTIONS else "")
        if asked:
            counts = dict(updates.get("ask_counts") or state.get("ask_counts") or {})
            counts[asked] = counts.get(asked, 0) + 1
            extra["ask_counts"] = counts
            extra["awaiting_slot"] = asked
        elif plan.action in PRESERVE_AWAITING:
            # Saying "take your time" is not asking anything, and it must not
            # discard the question they are taking their time over.
            pass
        elif plan.action not in FINAL_ACTIONS:
            extra["awaiting_slot"] = ""

        if plan.preamble:
            extra["survey_started"] = True

        # The outcome must be built from what this turn just decided, not from
        # the state it started with. A question declined on the very turn that
        # closes the call would otherwise be reported as never answered, which
        # reads as a call that ran out of time rather than a member who chose
        # not to say.
        settled = {**state, **updates, **extra}

        # Pull out any CallAgentField events accumulated during recording so they
        # can be combined with signal events rather than overwritten by them.
        field_events: list[dict] = updates.pop("metadata_events", [])

        if plan.action in TRANSFER_ACTIONS:
            disposition = _ACTION_DISPOSITION[plan.action]
            reason = _TRANSFER_REASON[plan.action]
            signal = self.signal_transfer(
                settled,
                message,
                reason,
                initiator="Caller",
                disposition=disposition,
                output_data=self._outcome(
                    settled, disposition=disposition, reason=reason
                ),
            )
            return {
                **self.persisted(),
                **updates,
                **extra,
                **signal,
                "metadata_events": field_events + signal.get("metadata_events", []),
            }

        if plan.action in FINAL_ACTIONS:
            disposition = _ACTION_DISPOSITION.get(
                plan.action
            ) or self._survey_disposition(settled)
            signal = self.signal_complete(
                settled,
                message,
                disposition=disposition,
                output_data=self._outcome(
                    settled, disposition=disposition, reason=plan.action.value
                ),
            )
            return {
                **self.persisted(),
                **updates,
                **extra,
                **signal,
                "metadata_events": field_events + signal.get("metadata_events", []),
            }

        result = {**self.persisted(), **updates, **extra, **self.speak(state, message)}
        if field_events:
            result["metadata_events"] = field_events
        return result

    def _end(
        self,
        state: SurveyState,
        message: str,
        *,
        disposition: str,
        reason: str,
        updates: dict | None = None,
    ) -> dict:
        """Stop the call now, keeping every answer already recorded."""
        settled = {**state, **(updates or {})}
        return {
            **self.persisted(),
            **(updates or {}),
            **self.signal_complete(
                settled,
                message,
                disposition=disposition,
                escalation_reason=reason if disposition == _ENDED_EARLY else "",
                output_data=self._outcome(
                    settled, disposition=disposition, reason=reason
                ),
            ),
        }

    # ── outcome ──────────────────────────────────────────────────────────

    def _survey_disposition(self, state: SurveyState) -> str:
        outstanding = outstanding_questions(
            self.spec,
            answers=self._answers,
            declined=tuple(state.get("declined") or ()),
            payload_lookup=lambda slot: self.payload_value(state, slot),
        )
        complete = not outstanding and not (state.get("declined") or ())
        return _SURVEYED if complete else _PARTIAL

    def _outcome(self, state: SurveyState, *, disposition: str, reason: str) -> dict:
        payload_lookup = lambda slot: self.payload_value(state, slot)
        answers = {
            slot: value
            for slot, value in self._answers.items()
            if slot in self.spec.question_slots
        }
        declined = [
            slot
            for slot in (state.get("declined") or [])
            if slot in self.spec.question_slots
        ]
        return {
            "call_outcome": {
                "status": "incomplete" if disposition == _ENDED_EARLY else "complete",
                "disposition": disposition,
                "reason": reason,
                "workflow_subtype": state.get("workflow_subtype")
                or "MEMBER_SATISFACTION_SURVEY",
                # The work-item facts that decided which questions this member
                # was asked, so a reader can see why question 5 was or was not
                # put without going back to the work item.
                "gating_facts": {
                    slot: payload_lookup(slot)
                    for slot in self.spec.condition_payload_slots
                },
                "answers": answers,
                "declined_questions": declined,
                "skipped_questions": [
                    {
                        "slot": skipped.slot,
                        "node": skipped.node,
                        "reason": skipped.reason,
                    }
                    for skipped in skipped_questions(
                        self.spec, answers=self._answers, payload_lookup=payload_lookup
                    )
                ],
                "missing_questions": outstanding_questions(
                    self.spec,
                    answers=self._answers,
                    declined=tuple(declined),
                    payload_lookup=payload_lookup,
                ),
                "visited_nodes": list(self._visited),
                # What the call did not finish, which is not the same as what it
                # did not say. The line about member services is a promise to
                # pass something on; the passing on happens here, in a list a
                # person works through, so an acknowledged request stays in it.
                "open_intents": unfinished(self._pending_intents),
            }
        }
