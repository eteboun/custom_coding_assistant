"""Backend failures, independent of agent tool semantics."""

from enum import StrEnum


class BackendUsageErrorScope(StrEnum):
    GENERAL = "general"
    SPECIFIC = "specific"


class BackendDeveloperError(Exception):
    """A backend dependency or invariant failed; not caused by tool arguments."""


class BackendUsageError(Exception):
    """An operation cannot be performed with the supplied arguments."""

    def __init__(
        self,
        message: str,
        *,
        error_key: str | None = None,
        scope: BackendUsageErrorScope = BackendUsageErrorScope.SPECIFIC,
    ):
        scope = BackendUsageErrorScope(scope)
        if scope is BackendUsageErrorScope.GENERAL and not error_key:
            raise ValueError("General backend usage errors require an error_key")
        super().__init__(message)
        self.error_key = error_key
        self.scope = scope
