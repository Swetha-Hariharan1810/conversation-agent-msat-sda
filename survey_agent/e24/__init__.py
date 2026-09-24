"""Expert24 TraversalService integration: client, models, adapters, errors."""

from .adapter import (
    DefaultRequestBuilder,
    DefaultResponseAdapter,
    RequestBuilder,
    ResponseAdapter,
    plain,
)
from .client import E24Client
from .errors import (
    E24Error,
    E24HTTPError,
    E24ProtocolError,
    E24Rejected,
    E24Unavailable,
    E24UncertainOutcome,
)
from .models import (
    AnswerOption,
    Completion,
    Conclusion,
    QARecord,
    QAResult,
    Question,
    QuestionKind,
    Step,
    TraversalHandles,
)

__all__ = [
    "AnswerOption",
    "Completion",
    "Conclusion",
    "DefaultRequestBuilder",
    "DefaultResponseAdapter",
    "E24Client",
    "E24Error",
    "E24HTTPError",
    "E24ProtocolError",
    "E24Rejected",
    "E24Unavailable",
    "E24UncertainOutcome",
    "QAResult",
    "QARecord",
    "Question",
    "QuestionKind",
    "RequestBuilder",
    "ResponseAdapter",
    "Step",
    "TraversalHandles",
    "plain",
]
