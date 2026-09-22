from abc import abstractmethod, ABC
from typing import Any

class LogElement(ABC):
    @abstractmethod
    def to_log(self) -> Any:
        ...

class ContextElement(ABC):
    @abstractmethod
    def to_context(self) -> Any:
        ...

class RecoverableError(Exception):
    pass

class CommandError(RecoverableError):
    pass

class MaxIterationsError(RecoverableError):
    pass

class LogError(RecoverableError):
    pass

class ToolEnvironmentError(RecoverableError):
    pass

class ConfigError(RecoverableError):
    pass
