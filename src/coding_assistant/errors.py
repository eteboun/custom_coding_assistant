"""Recoverable errors exposed by the assistant and its runtime."""


class RecoverableError(Exception):
    pass


class CommandError(RecoverableError):
    pass


class MaxIterationsError(RecoverableError):
    pass


class LogError(RecoverableError):
    pass
