import subprocess
import ast
import inspect
import sys

from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass

from config import repo_path
from tools.schemas import Symbol, SymbolKind, FunctionTool
from tools.utils import (_resolve_path, _symbol_matches,
                         _search_files_containing_terms, _parse_python_file,
                         _is_allowed_filepath)

class FunctionToolClass:

    @staticmethod
    def tool(
            tool_description: str,
            property_descriptions: dict,
            additional_properties: bool
    ) -> Callable:

        def decorator(func):

            tool_data = FunctionTool.from_func(
                func=func,
                tool_description=tool_description,
                property_descriptions=property_descriptions,
                additional_properties=additional_properties
            )

            func.is_tool = True
            func.tool_data = tool_data.serialize()

            return func

        return decorator

    @staticmethod
    @tool(
        tool_description=(
                "Read a known text file, optionally within a line range. "
                "Use directly when the file path is provided or already known."
        ),
        property_descriptions={
            "path": "Repository-relative file path.",
            "start_line": "Optional 1-based starting line.",
            "end_line": "Optional 1-based ending line, inclusive.",
        },
        additional_properties=False,
    )
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

    @staticmethod
    @tool(
        tool_description=(
                "List files and directories inside a known repository directory. "
                "Use only when the relevant file or directory entry is unknown. "
                "Never use this tool to verify, locate, or inspect a file path explicitly provided by the user."
        ),
        property_descriptions={
            "path": "Repository-relative directory path. Use '.' for the root."
        },
        additional_properties=False,
    )
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

    @staticmethod
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

                symbols += FunctionToolClass._walk_symbols(
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

                symbols += FunctionToolClass._walk_symbols(
                    node=child,
                    curr_notation=next_notation,
                    parent_kind=kind,
                    path=path,
                    search_notation=search_notation,
                    allow_unqualified=allow_unqualified,
                )

        return symbols

    @staticmethod
    @tool(
        tool_description=(
            "Search repository contents for text or regex matches when the location is unknown. "
            "Do not use to locate or verify a user-provided file path."
        ),
        property_descriptions={
            "notation": (
                "Symbol name or qualified notation, e.g. 'run' or 'Assistant.run'."
            ),
        },
        additional_properties=False,
    )
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
                for symbol in FunctionToolClass._walk_symbols(
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

    @staticmethod
    @tool(
        tool_description=(
                "Read a Python symbol when both its file path and exact qualified name are known."
        ),
        property_descriptions={
            "path": "Repository-relative Python file path.",
            "notation": (
                "Exact qualified notation, e.g. 'Assistant.run' or 'Factory.losses'."
            ),
        },
        additional_properties=False,
    )
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

        symbols = FunctionToolClass._walk_symbols(
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

        read_result = FunctionToolClass.read_file(
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

    @staticmethod
    @tool(
        tool_description=(
            "Search repository contents for text or regex matches. "
            "Returns file paths, line numbers, and matching lines. "
            "Use for known text or references, not file-name lookup."
        ),
        property_descriptions={
            "query": "Text or regular expression to search for."
        },
        additional_properties=False,
    )
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

    @staticmethod
    @tool(
        tool_description=(
                "Replace an exact piece of existing file content. "
                "The text must occur exactly once within the selected line range. "
                "A successful result confirms that the replacement was applied; "
                "do not re-read solely to verify the replacement."
        ),
        property_descriptions={
            "path": "Repository-relative file path.",
            "old_text": (
                "Exact text copied from the file, preserving its content, "
                "whitespace, indentation, and line breaks."
            ),
            "new_text": (
                "Replacement text with the intended whitespace, indentation, "
                "and line breaks."
            ),
            "start_line": "Optional 1-based starting line.",
            "end_line": "Optional 1-based ending line, inclusive.",
        },
        additional_properties=False,
    )
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

    @staticmethod
    @tool(
        tool_description=(
            "Create a new file. Fails if the path already exists."
        ),
        property_descriptions={
            "path": "Repository-relative path for the new file.",
            "content": "Complete initial content of the file.",
        },
        additional_properties=False,
    )
    def create_file(
        path: str,
        content: str,
    ) -> dict:
        full_path = _resolve_path(path)

        if full_path is None:
            return {
                "status": "error",
                "message": "Access to the file denied",
            }

        if full_path.exists():
            return {
                "status": "error",
                "message": f"File {full_path} already exists",
            }

        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

        return {
            "status": "success",
            "content": {
                "path": path,
            }
        }

    @staticmethod
    @tool(
        tool_description=(
                "Show the repository structure for broad exploration when relevant files are unknown. "
                "Never use this tool when the user has already provided the file path needed for the task."
        ),
        property_descriptions={},
        additional_properties=False,
    )
    def repo_tree() -> dict:
        files = []

        for path in repo_path.rglob("*"):
            relative_path = path.relative_to(repo_path)

            if _is_allowed_filepath(path):
                files.append(relative_path.as_posix())

        return {
            "status": "success",
            "content": files,
        }

    @staticmethod
    @tool(
        tool_description="Run a Python script.",
        property_descriptions={
            "path": "Repository-relative file path."
        },
        additional_properties=False,
    )
    def run_python_file(path: str) -> dict:

        full_path = _resolve_path(path)

        if full_path is None:
            return {
                "status": "error",
                "message": "Access to the file denied",
            }

        result = subprocess.run(
            [sys.executable, str(full_path)],
            capture_output=True,
            text=True,
            timeout=30
        )

        return {
            "status": "success",
            "content": {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        }

    @staticmethod
    @tool(
        tool_description=(
                    "Execute Python code from the repository root and return "
                    "its exit code, stdout, and stderr."
        ),
        property_descriptions={
            "code": "Python code to execute."
        },
        additional_properties=False,
    )
    def run_python_code(code: str) -> dict:

        try:
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "content": "Execution timed out after 30 seconds.",
            }

        return {
            "status": "success",
            "content": {
                "returncode": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
        }

    @staticmethod
    def tool_mapping() -> dict[str, Callable]:

        return {
            func.__name__: func
            for _, func in inspect.getmembers(FunctionToolClass, predicate=inspect.isfunction)
            if getattr(func, "is_tool", False)
        }

    @staticmethod
    def tools() -> list:

        return [
            func.tool_data
            for _, func in inspect.getmembers(FunctionToolClass, predicate=inspect.isfunction)
            if getattr(func, "is_tool", False)
        ]

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
    tool: str
    args: dict
    call_id: str

    def execute(self) -> FunctionToolOutput:
        result = FunctionToolClass.tool_mapping()[self.tool](**self.args)

        return FunctionToolOutput(
            call_id=self.call_id,
            output=str(result)
        )