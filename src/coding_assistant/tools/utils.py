import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..utils import OutputProtocol

Operation = Literal["update", "add", "delete"]

@dataclass
class FilePatch:
    operation: Operation
    path: str
    lines: list[str]

@dataclass
class Hunk:
    start: int
    end: int
    new_text: str


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
                status="error",
                message= "Access outside the repository is denied"
            )

        if full_path.name in self.blocked_files:
            return OutputProtocol(
                status="error",
                message=f"Path '{full_path}' is blocked"
            )

        relative_parts = full_path.relative_to(self.repo_path).parts

        if any(part in self.blocked_dirs for part in relative_parts):
            return OutputProtocol(
                status="error",
                message=f"Path '{full_path}' is blocked"
            )

        return OutputProtocol(
            status="success",
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
                status="error",
                message=f"Directory {path} does not exist",
            )

        if not full_path.is_dir():
            return OutputProtocol(
                status="error",
                message=f"{path} is not a directory"
            )

        return OutputProtocol(
            status="success",
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
                status="error",
                message=f"File {path} does not exist",
            )

        if not full_path.is_file():
            return OutputProtocol(
                status="error",
                message=f"{path} is not a file",
            )

        return OutputProtocol(
            status="success",
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

def _strip_final_newline(text: str) -> str:
    if text.endswith("\r\n"):
        return text[:-2]

    if text.endswith("\n"):
        return text[:-1]

    return text