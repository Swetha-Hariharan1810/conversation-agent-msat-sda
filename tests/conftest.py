"""Root test configuration.

One job: print, on every run, what the live gate found. Whether the live tests
are going to run is decided by an environment flag and a ``.env`` file, and a
directory of skips with no explanation is the kind of green run that gets
mistaken for a passing one.

The hook lives here rather than in ``tests/live/conftest.py`` because pytest only
calls ``pytest_report_header`` on conftests it has loaded by the time the header
is written — which, for a plain ``pytest``, does not include one nested a
directory deeper.
"""

from __future__ import annotations

from .live import environment as env


def pytest_report_header(config) -> str:
    return env.summary()
