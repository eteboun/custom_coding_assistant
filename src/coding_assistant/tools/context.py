from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, get_args

from ..utils import LogElement, ContextElement

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

class UpdateScope(StrEnum):
    REPOSITORY = "repository"
    FILE = "file"

class Operation(StrEnum):
    UPDATE = "update"
    DELETE = "delete"
    ADD = "add"

class Invalidation(StrEnum):
    REFRESH = "refresh"
    DISCARD = "discard"


@dataclass(frozen=True)
class Mutation(LogElement):
    path: str
    type: Operation

    def to_log(self) -> dict:
        return {
            "path": self.path,
            "type": self.type.value
        }

Status = Literal[
    "success", "error", "denied"
]

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

        if self.status == "success" and self.content is None:
            raise ValueError("Successful output must contain content")

        if self.status in ("error", "denied") and self.message is None:
            raise ValueError("Unsuccessful output must contain a message")

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
            "status": self.status,
            "content": (
                self.content.to_log()
                if isinstance(self.content, LogElement)
                else self.content
            ),
            "message": self.message
        }

    def to_context(self) -> dict:
        return {
            "status": self.status,
            "content": (
                self.content.to_log()
                if isinstance(self.content, LogElement)
                else self.content
            ),
            "message": self.message
        }

    def is_fail(self) -> bool:
        return self.status == "error"


@dataclass
class ToolCall(LogElement, ContextElement):
    name: str
    args: dict

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
