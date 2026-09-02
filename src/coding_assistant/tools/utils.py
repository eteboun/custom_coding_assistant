import inspect
import ast
from pathlib import Path
from typing import Any, get_args

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
    ) -> dict:
        full_path = (self.repo_path / path).resolve()

        if not full_path.is_relative_to(self.repo_path):
            return {
                "status": "error",
                "message": "Access outside the repository is denied",
            }

        if full_path.name in self.blocked_files:
            return {
                "status": "error",
                "message": f"Path '{full_path}' is blocked"
            }

        relative_parts = full_path.relative_to(self.repo_path).parts

        if any(part in self.blocked_dirs for part in relative_parts):
            return {
                "status": "error",
                "message": f"Path '{full_path}' is blocked"
            }

        return {
            "status": "success",
            "content": full_path
        }

    def resolve_dir(
            self,
            path: str
    ) -> dict:
        resolved_path = self.resolve_path(
            path=path
        )

        if resolved_path["status"] == "error":
            return resolved_path

        full_path = resolved_path["content"]

        if not full_path.exists():
            return {
                "status": "error",
                "message": f"Directory {path} does not exist",
            }

        if not full_path.is_dir():
            return {
                "status": "error",
                "message": f"{path} is not a directory",
            }

        return {
            "status": "success",
            "content": full_path,
        }

    def resolve_file(
            self,
            path: str
    ) -> dict:
        resolved_path = self.resolve_path(
            path=path
        )

        if resolved_path["status"] == "error":
            return resolved_path

        full_path = resolved_path["content"]

        if not full_path.exists():
            return {
                "status": "error",
                "message": f"File {path} does not exist",
            }

        if not full_path.is_file():
            return {
                "status": "error",
                "message": f"{path} is not a file",
            }

        return {
            "status": "success",
            "content": full_path,
        }

    def is_allowed_filepath(
            self,
            path: Path
    ) -> bool:
        resolved_file = self.resolve_file(
            path=path.as_posix()
        )

        return resolved_file["status"] == "success"

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

            if resolved_file["status"] == "error":
                continue

            full_path = resolved_file["content"]

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
