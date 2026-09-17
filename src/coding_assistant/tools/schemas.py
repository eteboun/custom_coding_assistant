from collections.abc import Callable
from typing import Self
from dataclasses import dataclass
from enum import StrEnum

from ..utils import OutputProtocol

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
class Parameters:
    properties: dict[str, dict]
    required: list[str]
    additional_properties: bool

    type: str = "object"


@dataclass(frozen=True)
class Metadata:
    update_scope: UpdateScope | None
    update_when: dict[Operation, Invalidation]
    mutative: bool = False


@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    parameters: Parameters
    strict: bool
    metadata: Metadata

    @classmethod
    def from_func(cls,
                  func: Callable,
                  description: str,
                  parameters: Parameters,
                  strict: bool,
                  metadata: Metadata
                  ) -> Self:
        name = func.__name__
        return cls(
            name=name,
            description=description,
            parameters=parameters,
            strict=strict,
            metadata=metadata
        )

@dataclass(frozen=True)
class FilePatch:
    operation: Operation
    path: str
    lines: list[str]

@dataclass(frozen=True)
class Hunk:
    start: int
    end: int
    new_text: str


@dataclass(frozen=True)
class Mutation:
    path: str
    type: Operation


@dataclass(frozen=True)
class ToolOutput:
    output: OutputProtocol
    files: tuple[str, ...] = ()
    mutations: tuple[Mutation, ...] = ()
    mutation_summary: str | None = None


@dataclass
class ToolCall:
    name: str
    args: dict

    mutation_summary: str | None = None

    def __post_init__(self):
        self.mutation_summary = self.args.pop("change_summary", None)
