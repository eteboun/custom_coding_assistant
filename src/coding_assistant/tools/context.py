from dataclasses import dataclass
from typing import Any, Literal, get_args

from ..utils import LogElement, ContextElement
from ..mutation import Mutation


Status = Literal["success", "error", "denied"]

@dataclass(frozen=True)
class LearningMetadata(LogElement):
    persistent: bool = False
    key: str | None = None

    def to_log(self) -> dict:
        return {
            "persistent": self.persistent,
            "key": self.key
        }

class ToolUsageError(Exception):
    def __init__(
        self,
        message: str,
        *,
        learning: LearningMetadata | None = None,
    ):
        super().__init__(message)
        self.learning = (
            learning
            if learning is not None
            else LearningMetadata()
        )

@dataclass(frozen=True)
class ToolOutput(LogElement, ContextElement):
    status: Status
    content: Any = None
    message: str | None = None

    files: tuple[str, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    learning_metadata: LearningMetadata | None = None

    def __post_init__(self):
        if self.status not in get_args(Status):
            raise ValueError(f"Invalid status: {self.status}")

        if self.status == "error" and self.message is None:
            raise ValueError("Error output must contain a message")

        if self.status == "error" and self.learning_metadata is None:
            raise ValueError("Error output must contain a learning metadata")

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
            "learning_metadata": (
                self.learning_metadata.to_log()
                if self.learning_metadata is not None
                else None
            ),
            **self.outcome,
        }

    def to_context(self) -> dict:
        return {
            **self.outcome,
            "mutations": [mutation.to_log() for mutation in self.mutations],
        }

    def is_fail(self) -> bool:
        return self.status == "error"


@dataclass
class ToolCall(LogElement, ContextElement):
    name: str
    args: dict
    id: str

    mutation_summary: str | None = None

    def __post_init__(self):
        self.mutation_summary = self.args.pop("change_summary", None)

    def to_log(self) -> dict:
        return {
            "name": self.name,
            "args": self.args,
            "mutation_summary": self.mutation_summary
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

    def is_fail(self) -> bool:
        return self.output.is_fail()

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
