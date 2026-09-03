import inspect
import ast
from pathlib import Path
from typing import Any, get_args, override
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pydantic import BaseModel, ConfigDict, Field
from enum import StrEnum

class Replacement(BaseModel):

    model_config = ConfigDict(extra="forbid")

    old_text: str
    new_text: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    old_text_start: int | None = Field(default=None, ge=0)
    old_text_end: int | None = Field(default=None, ge=0)

class Status(StrEnum):

    SUCCESS = "success"
    ERROR = "error"

class Serializable(ABC):

    @abstractmethod
    def serialize(self) -> Any:
        ...

@dataclass
class OutputProtocol(Serializable):

    status: Status
    content: Any = None
    message: str | None = None

    def __post_init__(self):
        if self.status == Status.SUCCESS and self.content is None:
            raise ValueError("Successful output must contain content")

        if self.status == Status.ERROR and self.message is None:
            raise ValueError("Error output must contain a message")

    @override
    def serialize(self) -> dict:
        serialized: dict[str, Any] = {
            "status": self.status.value
        }

        if self.content is not None:
            if isinstance(self.content, Serializable):
                serialized["content"] = self.content.serialize()

            else:
                serialized["content"] = self.content

        if self.message is not None:
            serialized["message"] = self.message

        return serialized

    def is_fail(self) -> bool:
        return self.status == Status.ERROR

class Pather:

    def __init__(self,
                 repo_path: Path,
                 blocked_files: list[str],
                 blocked_dirs: list[str]
                 ) -> None:

        self.repo_path = repo_path
        self.blocked_files = blocked_files
        self.blocked_dirs = blocked_dirs

    def resolve_path(
            self,
            path: str,
    ) -> OutputProtocol:
        full_path = (self.repo_path / path).resolve()

        if not full_path.is_relative_to(self.repo_path):
            return OutputProtocol(
                status=Status.ERROR,
                message= "Access outside the repository is denied"
            )

        if full_path.name in self.blocked_files:
            return OutputProtocol(
                status=Status.ERROR,
                message=f"Path '{full_path}' is blocked"
            )

        relative_parts = full_path.relative_to(self.repo_path).parts

        if any(part in self.blocked_dirs for part in relative_parts):
            return OutputProtocol(
                status=Status.ERROR,
                message=f"Path '{full_path}' is blocked"
            )

        return OutputProtocol(
            status=Status.SUCCESS,
            content=full_path
        )

    def resolve_dir(
            self,
            path: str
    ) -> OutputProtocol:

        resolved_path = self.resolve_path(
            path=path
        )

        if resolved_path.is_fail():
            return resolved_path

        full_path = resolved_path.content

        if not full_path.exists():
            return OutputProtocol(
                status=Status.ERROR,
                message=f"Directory {path} does not exist",
            )

        if not full_path.is_dir():
            return OutputProtocol(
                status=Status.ERROR,
                message=f"{path} is not a directory"
            )

        return OutputProtocol(
            status=Status.SUCCESS,
            content=full_path,
        )

    def resolve_file(
            self,
            path: str
    ) -> OutputProtocol:
        resolved_path = self.resolve_path(
            path=path
        )

        if resolved_path.is_fail():
            return resolved_path

        full_path = resolved_path.content

        if not full_path.exists():
            return OutputProtocol(
                status=Status.ERROR,
                message=f"File {path} does not exist",
            )

        if not full_path.is_file():
            return OutputProtocol(
                status=Status.ERROR,
                message=f"{path} is not a file",
            )

        return OutputProtocol(
            status=Status.SUCCESS,
            content=full_path,
        )

    def is_allowed_filepath(
            self,
            path: Path
    ) -> bool:
        resolved_file = self.resolve_file(
            path=path.as_posix()
        )

        return not resolved_file.is_fail()

    def search_files_containing_terms(
            self,
            terms: list[str],
            extension: str = ".py"
    ) -> list[Path]:

        found_files: list[Path] = []

        for path in self.repo_path.rglob(f"*{extension}"):
            relative_path = path.relative_to(self.repo_path)
            resolved_file = self.resolve_file(
                path=relative_path.as_posix()
            )

            if resolved_file.is_fail():
                continue

            full_path = resolved_file.content

            code = full_path.read_text(encoding="utf-8")

            if all(term in code for term in terms):
                found_files.append(full_path)

        return found_files

def parse_python_file(path: Path) -> ast.Module:
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read())

def symbol_matches(
    name: str,
    notation: str,
    search_notation: str,
    allow_unqualified: bool,
) -> bool:
    return (
        search_notation == notation
        or (
            allow_unqualified
            and search_notation == name
        )
    )

_PYTHON_TO_JSON_SCHEMA_TYPE = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "null",
}

def to_json_schema_type(annotation: Any) -> list[str]:
    if annotation is inspect._empty:
        raise TypeError("Parameter annotation is required")

    args = get_args(annotation)

    if not args:
        args = (annotation,)

    try:
        return [
            _PYTHON_TO_JSON_SCHEMA_TYPE[arg]
            for arg in args
        ]
    except KeyError as exc:
        raise TypeError(
            f"Unsupported parameter type: {annotation}"
        ) from exc
