import subprocess
import ast
import inspect

from enum import StrEnum
from dataclasses import dataclass
from typing import Self
from collections.abc import Callable
from pathlib import Path

from config import repo_path
from tools.utils import (_resolve_path, _symbol_matches,
                         _search_files_containing_terms, _parse_python_file,
                         _to_json_schema_type)

class FunctionToolNames(StrEnum):
    READ_FILE = "read_file"
    LIST_FILES = "list_files"
    SEARCH_CODE = "search_code"
    SEARCH_SYMBOL = "search_symbol"
    READ_SYMBOL = "read_symbol"
    REPLACE_IN_FILE = "replace_in_file"

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

    tool: FunctionToolNames
    args: dict
    call_id: str

    def execute(self) -> FunctionToolOutput:
        result = _mapping[self.tool](**self.args)

        return FunctionToolOutput(
            call_id=self.call_id,
            output=str(result)
        )


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
            types = _to_json_schema_type(param.annotation)

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

def read_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict:
    full_path = _resolve_path(path)

    if full_path is None:
        return {
            "status": "error",
            "message": "Access to the file denied",
        }

    with open(full_path, encoding="utf-8") as f:
        lines = f.readlines()

    start = start_line - 1 if start_line is not None else 0
    end = end_line if end_line is not None else len(lines)

    numbered_line_group = zip(
        range(start + 1, end + 1),
        lines[start:end]
    )

    numbered_lines = []
    for num, line in numbered_line_group:
        numbered_lines.append(
            f"{num} | {line}"
        )

    return {
        "status": "success",
        "content": "".join(numbered_lines)
    }

def list_files(path: str) -> dict:
    full_path = _resolve_path(path)

    if full_path is None:
        return {
            "status": "error",
            "message": "Access to the file denied",
        }

    return {
        "status": "success",
        "content": [
            e.name
            for e in full_path.iterdir()
        ]
    }

def _walk_symbols(
        node: ast.AST,
        path: Path,
        search_notation: str,
        allow_unqualified: bool,
        curr_notation: str | None = None,
        parent_kind: SymbolKind | None = None,
) -> list[Symbol]:
    symbols: list[Symbol] = []

    for child in ast.iter_child_nodes(node):

        if isinstance(child, ast.ClassDef):
            name = child.name
            next_notation = (
                f"{curr_notation}.{name}"
                if curr_notation is not None
                else name
            )

            if _symbol_matches(
                name=name,
                notation=next_notation,
                search_notation=search_notation,
                allow_unqualified=allow_unqualified,
            ):
                assert child.end_lineno is not None
                symbols.append(
                    Symbol(
                        path=path,
                        notation=next_notation,
                        kind=SymbolKind.CLASS,
                        start_line=child.lineno,
                        end_line=child.end_lineno,
                    )
                )

            symbols += _walk_symbols(
                node=child,
                curr_notation=next_notation,
                parent_kind=SymbolKind.CLASS,
                path=path,
                search_notation=search_notation,
                allow_unqualified=allow_unqualified
            )

        elif (
                isinstance(child, ast.FunctionDef)
                or isinstance(child, ast.AsyncFunctionDef)
        ):
            name = child.name

            next_notation = (
                f"{curr_notation}.{name}"
                if curr_notation is not None
                else name
            )

            kind = (
                SymbolKind.METHOD
                if parent_kind == SymbolKind.CLASS
                else SymbolKind.FUNCTION
            )

            if _symbol_matches(
                name=name,
                notation=next_notation,
                search_notation=search_notation,
                allow_unqualified=allow_unqualified,
            ):
                assert child.end_lineno is not None
                symbols.append(
                    Symbol(
                        path=path,
                        notation=next_notation,
                        kind=kind,
                        start_line=child.lineno,
                        end_line=child.end_lineno,
                    )
                )

            symbols += _walk_symbols(
                node=child,
                curr_notation=next_notation,
                parent_kind=kind,
                path=path,
                search_notation=search_notation,
                allow_unqualified=allow_unqualified,
            )

    return symbols

def search_symbol(notation: str) -> dict:

    full_paths = _search_files_containing_terms(
        notation.split("."),
        extension=".py",
    )

    symbols: list[dict] = []
    errors: list[str] = []

    allow_unqualified = "." not in notation
    for full_path in full_paths:

        try:
            tree = _parse_python_file(path=full_path)
        except SyntaxError:
            errors.append(
                f"Failed to parse Python file: {full_path.relative_to(repo_path).as_posix()}"
            )
            continue

        symbols.extend(
            symbol.serialize()
            for symbol in _walk_symbols(
                search_notation=notation,
                allow_unqualified=allow_unqualified,
                path=full_path.relative_to(repo_path),
                node=tree,
            )
        )

    result = {
        "status": "success",
        "content": symbols,
    }

    if errors:
        result["errors"] = errors

    return result

def read_symbol(path: str, notation: str) -> dict:

    full_path = _resolve_path(path)
    if full_path is None:
        return {
            "status": "error",
            "message": "Access to the file denied",
        }

    try:
        tree = _parse_python_file(path=full_path)
    except SyntaxError:
        return {
            "status": "error",
            "message": f"Failed to parse Python file: {full_path.relative_to(repo_path).as_posix()}"
        }

    symbols = _walk_symbols(
        search_notation=notation,
        allow_unqualified=False,
        path=full_path.relative_to(repo_path),
        node=tree
    )

    if not symbols:
        return {
            "status": "error",
            "message": f"Symbol not found: {notation}"
        }

    if len(symbols) > 1:
        return {
            "status": "error",
            "message": f"Multiple symbols found: {notation}"
        }

    symbol_data = symbols[0]

    read_result = read_file(
        path=path,
        start_line=symbol_data.start_line,
        end_line=symbol_data.end_line
    )

    if read_result["status"] != "success":
        return read_result

    return {
        "status": "success",
        "content": {
            "notation": symbol_data.notation,
            "content": read_result["content"]
        }
    }

def search_code(query: str) -> str:
    try:
        process = subprocess.run(
            ["rg", "-n", query, str(repo_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
    except FileNotFoundError:
        return "ripgrep is not installed or not available in PATH"

    if process.returncode == 0:
        return process.stdout

    elif process.returncode == 1:
        return "No match found"

    else:
        return f"An error occurred: {process.stderr}"

def replace_in_file(
    path: str,
    old_text: str,
    new_text: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> dict:

    full_path = _resolve_path(path)

    if full_path is None:
        return {
            "status": "error",
            "message": "Access to the file denied",
        }

    with open(full_path, "r", encoding="utf-8") as file:
        lines = file.readlines()

    start = start_line - 1 if start_line is not None else 0
    end = end_line if end_line is not None else len(lines)

    target_piece = "".join(lines[start:end])

    count = target_piece.count(old_text)

    if count == 0:
        return {
            "status": "error",
            "message": f"No match found for {old_text} in {path}",
        }

    if count > 1:
        return {
            "status": "error",
            "message": f"Multiple matches found for {old_text} in {path}",
        }

    target_piece = target_piece.replace(old_text, new_text)

    new_content = (
        "".join(lines[:start])
        + target_piece
        + "".join(lines[end:])
    )

    with open(full_path, "w", encoding="utf-8") as file:
        file.write(new_content)

    return {
        "status": "success",
        "content": {
            "path": path,
            "updated_text": new_text,
            "start_line": start_line,
            "end_line": end_line
        }
    }

_mapping = {
    FunctionToolNames.READ_FILE: read_file,
    FunctionToolNames.LIST_FILES: list_files,
    FunctionToolNames.SEARCH_CODE: search_code,
    FunctionToolNames.SEARCH_SYMBOL: search_symbol,
    FunctionToolNames.READ_SYMBOL: read_symbol,
    FunctionToolNames.REPLACE_IN_FILE: replace_in_file,
}