"""Errors raised by services and translated to HTTP responses by the web layer."""


class ServiceError(Exception):
    """Base class for expected business errors."""

    def __init__(self, message=""):
        super().__init__(message)
        self.message = message


class NotFoundError(ServiceError):
    """The requested object does not exist (HTTP 404)."""


class ValidationError(ServiceError):
    """The request is invalid; ``message`` is shown to the user."""


class ReplaceRequired(ValidationError):
    """The action would remove existing data; repeat it with an explicit confirmation.

    ``conflicts`` lists what would be removed, in words for the user.
    """

    def __init__(self, message, conflicts=()):
        super().__init__(message)
        self.conflicts = list(conflicts)

