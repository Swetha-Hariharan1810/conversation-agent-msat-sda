"""Every survey this deployment can run, keyed by ``workflow_subtype``.

Adding a survey is adding a folder with a ``survey.yaml``; nothing registers it
in code. The catalogue is loaded and validated as a whole at startup, so a
broken file stops the deploy rather than the first call that needs it.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

import yaml
from pydantic import ValidationError

from .definition import SurveyDefinition

CATALOG = Path(__file__).resolve().parent.parent / "catalog"
FILENAME = "survey.yaml"


class SurveyConfigError(ValueError):
    """A survey file that cannot be loaded, naming the file."""


class UnknownSurvey(LookupError):
    def __init__(self, workflow_subtype: str, known: Iterable[str]) -> None:
        super().__init__(
            f"no survey for workflow_subtype {workflow_subtype!r}; "
            f"known: {', '.join(sorted(known)) or 'none'}"
        )
        self.workflow_subtype = workflow_subtype


def load_definition(path: Path) -> SurveyDefinition:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SurveyConfigError(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SurveyConfigError(f"{path}: expected a mapping at the top level")
    try:
        return SurveyDefinition.model_validate(data)
    except ValidationError as exc:
        raise SurveyConfigError(f"{path}: {exc}") from exc


class SurveyRegistry:
    def __init__(self, surveys: Iterable[SurveyDefinition]) -> None:
        self._surveys: dict[str, SurveyDefinition] = {}
        for survey in surveys:
            if survey.workflow_subtype in self._surveys:
                raise SurveyConfigError(
                    f"workflow_subtype {survey.workflow_subtype!r} is defined twice"
                )
            self._surveys[survey.workflow_subtype] = survey

    @classmethod
    def from_directory(cls, root: Path = CATALOG) -> SurveyRegistry:
        """Load every ``<root>/<survey>/survey.yaml``."""
        if not root.is_dir():
            raise SurveyConfigError(f"{root}: survey catalogue directory not found")
        return cls(load_definition(path) for path in sorted(root.glob(f"*/{FILENAME}")))

    def get(self, workflow_subtype: str) -> SurveyDefinition:
        try:
            return self._surveys[workflow_subtype]
        except KeyError:
            raise UnknownSurvey(workflow_subtype, self._surveys) from None

    def __contains__(self, workflow_subtype: object) -> bool:
        return workflow_subtype in self._surveys

    def __iter__(self) -> Iterator[SurveyDefinition]:
        return iter(self._surveys.values())

    def __len__(self) -> int:
        return len(self._surveys)
