"""Common contracts for log serialization and context formatting."""

from abc import ABC, abstractmethod
from typing import Any


class LogElement(ABC):
    @abstractmethod
    def to_log(self) -> Any:
        ...


class ContextElement(ABC):
    @abstractmethod
    def to_context(self) -> dict:
        ...


class FormattableContext(ABC):
    @abstractmethod
    def format_context(self) -> str:
        ...
