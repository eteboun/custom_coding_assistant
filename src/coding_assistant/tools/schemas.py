import inspect

from enum import StrEnum
from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path
from typing import Self

from .utils import to_json_schema_type

class SymbolKind(StrEnum):
    METHOD = "method"
    FUNCTION = "function"
    CLASS = "class"

@dataclass(frozen=True)
class Symbol:
    path: Path
    notation: str
    kind: SymbolKind
    start_line: int
    end_line: int

    def serialize(self) -> dict:
        return {
            "path": self.path.as_posix(),
            "kind": self.kind.value,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "notation": self.notation
        }


@dataclass(frozen=True)
class Property:
    name: str
    type: list[str]
    description: str


@dataclass(frozen=True)
class Parameters:
    properties: list[Property]
    required_properties: list[Property]
    additional_properties: bool

    def serialize(self) -> dict:
        return {
            "type": "object",
            "properties": {
                prop.name: {
                    "type": prop.type,
                    "description": prop.description
                } for prop in self.properties
            },
            "required": [
                prop.name
                for prop in self.required_properties
            ],
            "additionalProperties": self.additional_properties
        }

    @classmethod
    def from_func(cls,
                  func: Callable,
                  property_descriptions: dict[str, str],
                  additional_properties: bool
                  ) -> Self:

        properties: list[Property] = []
        required_properties: list[Property] = []

        sig = inspect.signature(func)
        for name, param in sig.parameters.items():
            if name == "self":
                continue

            types = to_json_schema_type(param.annotation)

            description = property_descriptions.get(name)
            if description is None:
                raise ValueError(
                    "description cannot be empty"
                )

            property_ = Property(
                name=name,
                type=types,
                description=description,
            )

            properties.append(property_)

            has_default = param.default is not inspect._empty
            if not has_default:
                required_properties.append(property_)

        return cls(
            properties=properties,
            required_properties=required_properties,
            additional_properties=additional_properties
        )

@dataclass(frozen=True)
class ToolSchema:
    name: str
    description: str
    parameters: Parameters

    def serialize(self) -> dict:
        return {
            "type": "function",
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters.serialize(),
        }

    @classmethod
    def from_func(cls,
                  func: Callable,
                  tool_description: str,
                  property_descriptions: dict[str, str],
                  additional_properties: bool
                  ) -> Self:
        name = func.__name__

        parameters = Parameters.from_func(
            func=func,
            property_descriptions=property_descriptions,
            additional_properties=additional_properties
        )

        return cls(
            name=name,
            description=tool_description,
            parameters=parameters
        )