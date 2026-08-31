import inspect
import ast
from pathlib import Path
from typing import Any, get_args

from config import repo_path

_BLOCKED_FILES = {
    ".env",
}

_BLOCKED_DIRS = {
    ".git",
    ".venv",
    ".idea",
    "venv",
    "__pycache__",
    "logs"
}

def _resolve_path(path: str) -> Path | None:
    full_path = (repo_path / path).resolve()

    if not full_path.is_relative_to(repo_path):
        return None

    if full_path.name in _BLOCKED_FILES:
        return None

    relative_parts = full_path.relative_to(repo_path).parts

    if any(part in _BLOCKED_DIRS for part in relative_parts):
        return None

    return full_path

def _is_allowed_filepath(path: Path) -> bool:
    full_path = _resolve_path(path.as_posix())

    if full_path is None:
        return False

    return full_path.is_file()

def _parse_python_file(path: Path) -> ast.Module:
    with open(path, encoding="utf-8") as f:
        return ast.parse(f.read())

def _symbol_matches(
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

def _search_files_containing_terms(
    terms: list[str],
    extension: str = ".py",
) -> list[Path]:

    found_files: list[Path] = []

    for path in repo_path.rglob(f"*{extension}"):
        relative_path = path.relative_to(repo_path)
        full_path = _resolve_path(str(relative_path))

        if full_path is None:
            continue

        code = full_path.read_text(encoding="utf-8")

        if all(term in code for term in terms):
            found_files.append(full_path)

    return found_files

_PYTHON_TO_JSON_SCHEMA_TYPE = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
    type(None): "null",
}

def _to_json_schema_type(annotation: Any) -> list[str]:
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
