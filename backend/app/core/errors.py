"""Domain-aware exceptions.

Each carries enough structure for the API layer to map it to a status code
without string-matching messages, and for the trace to record *why* something
failed rather than only that it did.
"""

from __future__ import annotations


class AltoError(Exception):
    """Base for every error this application raises deliberately."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, **context: object) -> None:
        super().__init__(message)
        self.message = message
        self.context = context

    def to_dict(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message, "context": self.context}


class ConfigurationError(AltoError):
    """The application is misconfigured. Raised at startup, never mid-request."""

    code = "configuration_error"


class PipelineError(AltoError):
    """A pipeline stage failed."""

    code = "pipeline_error"


class LLMError(AltoError):
    """A model call failed or returned something unusable."""

    status_code = 502
    code = "llm_error"


class StructuredOutputError(LLMError):
    """The model returned output that does not satisfy the required schema.

    Treated as a hard failure rather than something to paper over: a stage
    that cannot parse its own input should escalate, not guess.
    """

    code = "structured_output_error"


class BudgetExceededError(LLMError):
    """The daily spend ceiling was reached."""

    status_code = 429
    code = "budget_exceeded"


class RetrievalError(AltoError):
    status_code = 502
    code = "retrieval_error"


class GroundingError(AltoError):
    """A drafted answer made claims the evidence does not support."""

    code = "grounding_error"


class ToolError(AltoError):
    """A deterministic tool could not produce a result.

    Raised in preference to returning an approximate number. For EMI and
    valuation, refusing to answer is always better than answering wrongly.
    """

    status_code = 422
    code = "tool_error"


class NotFoundError(AltoError):
    status_code = 404
    code = "not_found"


class ConflictError(AltoError):
    """The requested change conflicts with existing state."""

    status_code = 409
    code = "conflict"


class AuthenticationError(AltoError):
    status_code = 401
    code = "unauthenticated"


class AuthorizationError(AltoError):
    status_code = 403
    code = "forbidden"
