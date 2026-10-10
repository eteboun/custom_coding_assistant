from dataclasses import dataclass
from typing import Any, Literal, get_args

from ..interfaces import LogElement, ContextElement
from ..mutation import Mutation


Status = Literal["success", "error", "denied"]

class ToolUsageError(Exception):
    pass

@dataclass(frozen=True)
class ToolOutput(LogElement, ContextElement):
    status: Status
    content: Any = None
    message: str | None = None

    files: tuple[str, ...] = ()
    mutations: tuple[Mutation, ...] = ()

    def __post_init__(self):
        if self.status not in get_args(Status):
            raise ValueError(f"Invalid status: {self.status}")

        if self.status == "error" and self.message is None:
            raise ValueError("Error output must contain a message")


    @property
    def outcome(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "content": self.content,
            "message": self.message,
        }

    def to_log(self) -> dict:
        return {
            "files": self.files,
            "mutations": [
                mutation.to_log()
                for mutation in self.mutations
            ],
            **self.outcome,
        }

    def to_context(self) -> dict:
        return {
            **self.outcome,
            "mutations": [mutation.to_log() for mutation in self.mutations],
        }



@dataclass
class ToolCall(LogElement, ContextElement):
    name: str
    args: dict
    id: str

    def to_log(self) -> dict:
        return {
            "name": self.name,
            "args": self.args,
        }

    def to_context(self) -> dict:
        return {
            "name": self.name,
            "args": self.args
        }

@dataclass
class ToolEvent(LogElement, ContextElement):
    call: ToolCall
    output: ToolOutput


    def to_log(self) -> dict:
        return {
            "call": self.call.to_log(),
            "output": self.output.to_log(),
        }

    def to_context(self):
        return {
            "call": self.call.to_context(),
            "output": self.output.to_context()
        }
