import subprocess
import inspect
from pathlib import Path
from enum import StrEnum
from dataclasses import dataclass
from typing import ClassVar, Self
from collections.abc import Callable

_repo_path = Path(__file__).resolve().parent

def _resolve_path(path: str) -> Path | None:
    full_path = (_repo_path / path).resolve()

    if not full_path.is_relative_to(_repo_path):
        return None

    return full_path

def read_file(path: str) -> str:
    full_path = _resolve_path(path)

    if full_path is None:
        return "Access to the file denied"

    return full_path.read_text(encoding='utf-8')

def list_files(path: str) -> list[str] | str:
    full_path = _resolve_path(path)

    if full_path is None:
        return "Access to the file denied"

    return [
        e.name
        for e in full_path.iterdir()
    ]

def search_code(query: str) -> str:
    try:
        process = subprocess.run(
            ["rg", "-n", query, str(_repo_path)],
            capture_output=True,
            text=True
        )
    except FileNotFoundError:
        return "ripgrep is not installed or not available in PATH"

    if process.returncode == 0:
        return process.stdout

    elif process.returncode == 1:
        return "No match found"

    else:
        return f"An error occurred: {process.stderr}"

class FunctionToolNames(StrEnum):
    READ_FILE = "read_file"
    LIST_FILES = "list_files"
    SEARCH_CODE = "search_code"

_PYTHON_TO_JSON_SCHEMA_TYPE = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "null",
}

def _to_json_schema_type(annotation: type) -> str:
    if annotation is inspect._empty:
        raise TypeError("Parameter annotation is required")

    try:
        return _PYTHON_TO_JSON_SCHEMA_TYPE[annotation]
    except KeyError:
        raise TypeError(
            f"Unsupported parameter type: {annotation}"
        )

@dataclass(frozen=True)
class FunctionToolOutput:
    call_id: str
    output: str

    def serialize(self) -> dict:
        return {
            "type": "function_call_output",
            "call_id": self.call_id,
            "output": self.output
        }

@dataclass(frozen=True)
class FunctionToolCall:

    _mapping: ClassVar[dict[
        FunctionToolNames, Callable
    ]] = {
        FunctionToolNames.READ_FILE: read_file,
        FunctionToolNames.LIST_FILES: list_files,
        FunctionToolNames.SEARCH_CODE: search_code
    }

    tool: FunctionToolNames
    args: dict
    call_id: str

    def execute(self) -> FunctionToolOutput:
        result = self._mapping[self.tool](**self.args)

        return FunctionToolOutput(
            call_id=self.call_id,
            output=str(result)
        )

@dataclass(frozen=True)
class Property:
    name: str
    type: str
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
            type_ = _to_json_schema_type(param.annotation)

            description = property_descriptions.get(name)
            if description is None:
                raise ValueError(
                    "description cannot be empty"
                )

            property_ = Property(
                name=name,
                type=type_,
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
class FunctionTool:
    name: FunctionToolNames
    description: str
    parameters: Parameters
    
    def serialize(self) -> dict:
        return {
            "type": "function",
            "name": self.name.value,
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
        name = FunctionToolNames(
            func.__name__
        )

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

@dataclass(frozen=True)
class FunctionTools:
    tools: list[FunctionTool]
    
    def serialize(self) -> list:
        return [
            tool.serialize()
            for tool in self.tools
        ]

available_tools = FunctionTools(
    tools=[
        FunctionTool.from_func(
            func=read_file,
            tool_description=(
                "Read the contents of a text file inside the current repository. "
                "Use this when you need to inspect the implementation of a known file."
            ),
            property_descriptions={
                "path": (
                    "Path to the file relative to the repository root, "
                    "for example 'src/auth.py'."
                )
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=list_files,
            tool_description=(
                "List files and directories at a path inside the current repository. "
                "Use this to explore the repository structure when you do not yet know "
                "which file is relevant."
            ),
            property_descriptions={
                "path": (
                    "Directory path relative to the repository root. "
                    "Use '.' for the repository root."
                )
            },
            additional_properties=False
        ),

        FunctionTool.from_func(
            func=search_code,
            tool_description=(
                "Search the current repository for an exact text or regular expression. "
                "Returns matching file paths, line numbers, and matching lines. "
                "Use this to locate symbols, function names, classes, imports, "
                "error messages, or other known pieces of text."
            ),
            property_descriptions={
                "query": (
                    "Text or regular expression to search for in the repository."
                )
            },
            additional_properties=False
        )
    ]
).serialize()