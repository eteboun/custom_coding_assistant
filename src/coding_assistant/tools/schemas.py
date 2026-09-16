from dataclasses import dataclass
from collections.abc import Callable
from typing import Self, Literal

from .event import UpdateScope, MutationType

@dataclass(frozen=True)
class Parameters:
    properties: dict[str, dict]
    required: list[str]
    additional_properties: bool

    type: str = "object"


@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    parameters: Parameters
    strict: bool
    update_scope: UpdateScope | None
    update_when: tuple[MutationType, ...]

    @classmethod
    def from_func(cls,
                  func: Callable,
                  description: str,
                  parameters: Parameters,
                  strict: bool,
                  update_scope: UpdateScope | None,
                  update_when: tuple[MutationType, ...]
                  ) -> Self:
        name = func.__name__

        return cls(
            name=name,
            description=description,
            parameters=parameters,
            strict=strict,
            update_scope=update_scope,
            update_when=update_when
        )

Operation = Literal["update", "add", "delete"]

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
