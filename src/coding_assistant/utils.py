from abc import abstractmethod, ABC
from typing import Any, Literal, override, get_args
from dataclasses import dataclass

class Serializable(ABC):

    @abstractmethod
    def serialize(self) -> Any:
        ...

Status = Literal["error", "success"]

@dataclass(frozen=True)
class OutputProtocol(Serializable):
    status: Status
    content: Any = None
    message: str | None = None

    def __post_init__(self):
        if self.status not in get_args(Status):
            raise ValueError(f"Invalid status: {self.status}")

        if self.status == "success" and self.content is None:
            raise ValueError("Successful output must contain content")

        if self.status == "error" and self.message is None:
            raise ValueError("Error output must contain a message")

    @override
    def serialize(self) -> dict:
        serialized: dict[str, Any] = {
            "status": self.status
        }

        if self.content is not None:
            if isinstance(self.content, Serializable):
                serialized["content"] = self.content.serialize()

            else:
                serialized["content"] = self.content

        if self.message is not None:
            serialized["message"] = self.message

        return serialized

    def is_fail(self) -> bool:
        return self.status == "error"

class RecoverableError(Exception):
    pass

class CommandError(RecoverableError):
    pass

class MaxIterationsError(RecoverableError):
    pass

class ToolUsageError(RecoverableError):
    pass

class ConfigError(RecoverableError):
    pass
