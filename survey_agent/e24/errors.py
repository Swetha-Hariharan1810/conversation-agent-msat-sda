"""Everything that can go wrong talking to Expert24, split by what the caller
should do about it.

The split that matters on a live call is between :class:`E24Unavailable` and
:class:`E24UncertainOutcome`. The first means the request never took effect, so
the caller may end the call cleanly or try again later. The second means a
state-changing request (``Member``, ``First``, ``Next``, ``Previous``) was sent
and we never learned whether Expert24 applied it — the traversal may already have
moved on. Retrying blindly would risk answering a question twice, so the client
never does; the engine decides how to recover.
"""

from __future__ import annotations


class E24Error(Exception):
    """Base for every Expert24 failure."""

    def __init__(self, message: str, *, operation: str) -> None:
        super().__init__(message)
        self.operation = operation


class E24Unavailable(E24Error):
    """Expert24 could not be reached, and nothing was applied."""


class E24UncertainOutcome(E24Error):
    """A state-changing request was sent but its result is unknown."""


class E24HTTPError(E24Error):
    """Expert24 (or the proxy in front of it) answered with an error status."""

    def __init__(self, message: str, *, operation: str, status: int) -> None:
        super().__init__(message, operation=operation)
        self.status = status


class E24ProtocolError(E24Error):
    """The response was not in a shape the adapter can read."""


class E24Rejected(E24Error):
    """Expert24 answered 200 but reported an error in the body."""
