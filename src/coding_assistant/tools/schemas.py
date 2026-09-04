from enum import StrEnum
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path
from typing import Self, override

from .utils import Serializable

class SymbolKind(StrEnum):
    METHOD = "method"
    FUNCTION = "function"
    CLASS = "class"

@dataclass(frozen=True)
class Symbol(Serializable):
    path: Path
    notation: str
    kind: SymbolKind
    start_line: int
    end_line: int

    @override
    def serialize(self) -> dict:
        return {
            "path": self.path.as_posix(),
            "kind": self.kind.value,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "notation": self.notation
        }

@dataclass(frozen=True)
class Parameters(Serializable):
    properties: dict[str, dict]
    required: list[str]
    additional_properties: bool

    @override
    def serialize(self) -> dict:
        return {
            "type": "object",
            "properties": self.properties,
            "required": self.required,
            "additionalProperties": self.additional_properties
        }

@dataclass(frozen=True)
class ToolSchema(Serializable):
    name: str
    description: str
    parameters: Parameters
    strict: bool

    @override
    def serialize(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters.serialize(),
            "strict": self.strict
        }

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