class ScientificBackendError(RuntimeError):
    """Base error for read-only scientific backend integration."""


class ScientificBackendDataError(ScientificBackendError):
    """Raised when backend status artifacts are missing or invalid."""
