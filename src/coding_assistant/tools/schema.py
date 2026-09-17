from collections.abc import Callable
from typing import Self
from dataclasses import dataclass

from .context import UpdateScope, Operation, Invalidation

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