"""Backend failures, independent of agent tool semantics."""


class BackendDeveloperError(Exception):
    """A backend dependency or invariant failed; not caused by tool arguments."""


class BackendUsageError(Exception):
    """An operation cannot be performed with the supplied arguments."""
