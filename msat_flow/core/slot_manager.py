"""Answer state and per-turn recording.

Everything the survey collects arrives from the member and goes through
normalise → validate → record. The only values that do not are the two the work
item brings: the policyholder's name and their risk tier, read through
``payload.resolve`` along declared paths and never inferred.
"""

from __future__ import annotations

from ..payload import resolve
from ..script.spec import SurveySpec
from ..slots.pipeline import accept
from ..state import SurveyState
from .models import SlotAttempt


class SlotManagerMixin:
    """Adds answer bookkeeping and recording to the base agent."""

    _slots: dict[str, SlotAttempt]
    _answers: dict[str, str]
    # Set by the concrete agent; policy and payload bindings are read from it.
    spec: SurveySpec

    # ── bookkeeping ──────────────────────────────────────────────────────

    def slot(self, name: str) -> SlotAttempt:
        if name not in self._slots:
            self._slots[name] = SlotAttempt(name)
        return self._slots[name]

    def slots_dict(self) -> dict[str, dict]:
        return {name: attempt.to_dict() for name, attempt in self._slots.items()}

    def answered(self, name: str) -> bool:
        return bool(self._answers.get(name))

    def answer(self, name: str) -> str:
        return self._answers.get(name, "")

    def exhausted(self, slot: str) -> bool:
        """Whether this question has been put as often as policy allows."""
        return self.slot(slot).is_exhausted(self.spec.policy.max_asks_per_slot)

    # ── the work item ────────────────────────────────────────────────────

    def payload_value(self, state: SurveyState, slot: str) -> str:
        """Look a work-item value up. No inference — see ``msat_flow/payload.py``."""
        return resolve(self.spec, state.get("input_data"), slot)

    # ── recording ────────────────────────────────────────────────────────

    def record(self, slot: str, raw: str) -> tuple[bool, str]:
        """Normalise, validate and store one member-stated answer.

        Returns ``(accepted, reason)``. A rejected answer counts as a failed
        attempt so the question is eventually left alone instead of looping.
        """
        result = accept(slot, raw)
        if result.accepted:
            self._answers[slot] = result.value
            self.slot(slot).record(result.value, success=True)
            return True, result.reason
        self.slot(slot).record(raw, success=False)
        return False, result.reason

    def record_many(self, values: dict[str, str]) -> tuple[list[str], dict[str, str]]:
        """Record every answer the member offered this turn, in any order.

        This is what lets a member answer three questions in one breath: we take
        whatever was said, not only the question we happened to have asked.
        """
        accepted: list[str] = []
        rejected: dict[str, str] = {}
        for slot, raw in (values or {}).items():
            ok, reason = self.record(slot, str(raw))
            if ok:
                accepted.append(slot)
            else:
                rejected[slot] = reason
        return accepted, rejected

    def forget(self, slot: str) -> None:
        """Drop an answer whose gating question has changed underneath it.

        If a member says they never looked at the resources after rating how
        helpful they were, the rating belongs to a question they should not have
        been asked. Keeping it would file an answer against a question the
        script says was skipped.
        """
        self._answers.pop(slot, None)
        self._slots.pop(slot, None)
