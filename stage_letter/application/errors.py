"""Application-layer errors for formal Stage Letter use-cases."""


class ApplicationServiceError(RuntimeError):
    """Base error for application-service orchestration failures."""


class ApplicationInvariantError(ApplicationServiceError):
    """Raised when a use-case request violates a frozen cross-entity invariant."""


class ApplicationNotFoundError(ApplicationServiceError):
    """Raised when a use-case requires a formal aggregate that does not exist."""
