from dataclasses import dataclass
from enum import StrEnum

from ..utils import OutputProtocol, Serializable, ContextElement

@dataclass(frozen=True)
class LearningMetadata(Serializable):
    persistent: bool = False
    key: str | None = None

    def serialize(self) -> dict:
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
class Mutation(Serializable):
    path: str
    type: Operation

    def serialize(self) -> dict:
        return {
            "path": self.path,
            "type": self.type.value
        }


@dataclass(frozen=True)
class ToolOutput(Serializable, ContextElement):
    output: OutputProtocol
    files: tuple[str, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    learning_metadata: LearningMetadata | None = None

    def serialize(self) -> dict:
        return {
            "files": self.files,
            "mutations": [
                mutation.serialize()
                for mutation in self.mutations
            ],
            "learning_metadata": self.learning_metadata.serialize()
        }

    def to_context(self) -> dict:
        return self.output.serialize()

    def is_fail(self) -> bool:
        return self.output.is_fail()


@dataclass
class ToolCall(Serializable, ContextElement):
    name: str
    args: dict

    mutation_summary: str | None = None

    def __post_init__(self):
        self.mutation_summary = self.args.pop("change_summary", None)

    def serialize(self) -> dict:
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
