from dataclasses import dataclass
from collections.abc import Callable
from typing import Self

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

    @classmethod
    def from_func(cls,
                  func: Callable,
                  description: str,
                  parameters: Parameters,
                  strict: bool
                  ) -> Self:
        name = func.__name__

        return cls(
            name=name,
            description=description,
            parameters=parameters,
            strict=strict
        )