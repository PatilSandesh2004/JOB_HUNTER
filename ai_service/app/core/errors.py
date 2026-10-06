"""Domain exceptions shared across services."""


class JobPilotError(Exception):
    """Base class for expected, user-facing failures."""


class NotFoundError(JobPilotError):
    pass


class LLMUnavailableError(JobPilotError):
    """Raised when no LLM is configured or every model in the fallback chain failed."""


class ResumeParseError(JobPilotError):
    pass
