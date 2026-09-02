import subprocess
import ast
import inspect
import json

from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass

from tools.schemas import Symbol, SymbolKind, ToolSchema
from tools.utils import (_symbol_matches,
                         _search_files_containing_terms, _parse_python_file,
                         _is_allowed_filepath, _resolve_file, _resolve_dir, _resolve_path)

class Tools:

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

        self.mapping = self._tool_mapping()
        self.datas = self._tool_datas()

    def _walk_symbols(
            self,
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

                symbols += self._walk_symbols(
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

                symbols += self._walk_symbols(
                    node=child,
                    curr_notation=next_notation,
                    parent_kind=kind,
                    path=path,
                    search_notation=search_notation,
                    allow_unqualified=allow_unqualified,
                )

        return symbols

    def _run_docker(self, command: list[str]) -> dict:
        docker_command = [
            "docker",
            "run",
            "--rm",

            "--user", "1000:1000",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",

            "--network", "none",

            "--memory", "512m",
            "--cpus", "1",
            "--pids-limit", "64",

            "--read-only",
            "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",

            "--mount",
            f"type=bind,source={self.repo_path},target=/workspace,readonly",

            "--workdir", "/workspace",

            "python:3.13-slim",
            *command,
        ]

        try:
            completed = subprocess.run(
                docker_command,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "message": "Execution timed out",
            }
        except FileNotFoundError:
            return {
                "status": "error",
                "message": "Docker is not installed or not in PATH",
            }

        return {
            "status": "success" if completed.returncode == 0 else "error",
            "content": {
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "returncode": completed.returncode,
            },
        }

    def _run_dockerized_file(self, path: Path) -> dict:
        relative_path = path.relative_to(self.repo_path)

        return self._run_docker([
            "python",
            relative_path.as_posix(),
        ])

    def _run_dockerized_code(self, code: str) -> dict:
        return self._run_docker([
            "python",
            "-c",
            code,
        ])

    def _tool_mapping(self) -> dict[str, Callable]:

        return {
            func.__name__: func
            for _, func in inspect.getmembers(self, predicate=inspect.ismethod)
            if getattr(func, "is_tool", False)
        }

    def _tool_datas(self) -> list:

        return [
            func.tool_data
            for _, func in inspect.getmembers(self, predicate=inspect.ismethod)
            if getattr(func, "is_tool", False)
        ]

    @staticmethod
    def _tool(
            tool_description: str,
            property_descriptions: dict,
            additional_properties: bool
    ) -> Callable:

        def decorator(func):

            tool_data = ToolSchema.from_func(
                func=func,
                tool_description=tool_description,
                property_descriptions=property_descriptions,
                additional_properties=additional_properties
            )

            func.is_tool = True
            func.tool_data = tool_data.serialize()

            return func

        return decorator

    @_tool(
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
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict:
        resolved_file = _resolve_file(path, self.repo_path)

        if resolved_file["status"] == "error":
            return resolved_file

        full_path = resolved_file["content"]

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

    @_tool(
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
    def list_files(self, path: str) -> dict:
        resolved_path = _resolve_dir(path, self.repo_path)

        if resolved_path["status"] == "error":
            return resolved_path

        full_path = resolved_path["content"]

        return {
            "status": "success",
            "content": [
                e.name
                for e in full_path.iterdir()
            ]
        }

    @_tool(
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
    def search_symbol(self, notation: str) -> dict:

        full_paths = _search_files_containing_terms(
            notation.split("."),
            extension=".py",
            repo_path=self.repo_path
        )

        symbols: list[dict] = []
        errors: list[str] = []

        allow_unqualified = "." not in notation
        for full_path in full_paths:

            try:
                tree = _parse_python_file(path=full_path)
            except SyntaxError:
                errors.append(
                    f"Failed to parse Python file: {full_path.relative_to(self.repo_path).as_posix()}"
                )
                continue

            symbols.extend(
                symbol.serialize()
                for symbol in self._walk_symbols(
                    search_notation=notation,
                    allow_unqualified=allow_unqualified,
                    path=full_path.relative_to(self.repo_path),
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

    @_tool(
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
    def read_symbol(self, path: str, notation: str) -> dict:

        resolved_file = _resolve_file(path, self.repo_path)

        if resolved_file["status"] == "error":
            return resolved_file

        full_path = resolved_file["content"]

        try:
            tree = _parse_python_file(path=full_path)
        except SyntaxError:
            return {
                "status": "error",
                "message": f"Failed to parse Python file: {full_path.relative_to(self.repo_path).as_posix()}"
            }

        symbols = self._walk_symbols(
            search_notation=notation,
            allow_unqualified=False,
            path=full_path.relative_to(self.repo_path),
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

        read_result = Tools.read_file(
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

    @_tool(
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
    def search_code(self, query: str) -> str:
        try:
            process = subprocess.run(
                ["rg", "-n", query, self.repo_path.as_posix()],
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

    @_tool(
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
        self,
        path: str,
        old_text: str,
        new_text: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> dict:

        resolved_file = _resolve_file(path, self.repo_path)

        if resolved_file["status"] == "error":
            return resolved_file

        full_path = resolved_file["content"]

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

    @_tool(
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
        self,
        path: str,
        content: str,
    ) -> dict:
        resolved_path = _resolve_path(path, self.repo_path)

        if resolved_path["status"] == "error":
            return resolved_path

        full_path = resolved_path["content"]

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

    @_tool(
        tool_description="Deletes the file with provided path.",
        property_descriptions={
            "path": "Repository-relative path for the file to be deleted.",
        },
        additional_properties=False
    )
    def delete_file(self, path: str) -> dict:
        resolved_file = _resolve_path(path, self.repo_path)

        if resolved_file["status"] == "error":
            return resolved_file

        full_path = resolved_file["content"]

        full_path.unlink()

        return {
            "status": "success",
            "content": {
                "path": path,
            }
        }

    @_tool(
        tool_description=(
                "Runs a command in an isolated Docker container "
                "with the repository as the working directory."
        ),
        property_descriptions={
            "command": (
                    "Command and arguments to execute, provided as a list. "
                    "Example: ['python', '-m', 'pytest']."
            )
        },
        additional_properties=False
    )
    def run_command(self, command: list[str]) -> dict:
        return self._run_docker(
            command=command
        )

    @_tool(
        tool_description=(
                "Show the repository structure for broad exploration when relevant files are unknown. "
                "Never use this tool when the user has already provided the file path needed for the task."
        ),
        property_descriptions={},
        additional_properties=False,
    )
    def repo_tree(self) -> dict:
        files = []

        for path in self.repo_path.rglob("*"):
            relative_path = path.relative_to(self.repo_path)

            if _is_allowed_filepath(path, self.repo_path):
                files.append(relative_path.as_posix())

        return {
            "status": "success",
            "content": files,
        }

    @_tool(
        tool_description="Run a Python script.",
        property_descriptions={
            "path": "Repository-relative file path."
        },
        additional_properties=False,
    )
    def run_python_file(self, path: str) -> dict:

        resolved_file = _resolve_file(path, self.repo_path)

        if resolved_file["status"] == "error":
            return resolved_file

        full_path = resolved_file["content"]

        if full_path.suffix != ".py":
            return {
                "status": "error",
                "message": f"File {full_path} is not a Python file"
            }

        return self._run_dockerized_file(
            path=full_path
        )

    @_tool(
        tool_description=(
                    "Execute Python code from the repository root and return "
                    "its exit code, stdout, and stderr."
        ),
        property_descriptions={
            "code": "Python code to execute."
        },
        additional_properties=False,
    )
    def run_python_code(self, code: str) -> dict:
        return self._run_dockerized_code(code)

@dataclass(frozen=True)
class ToolOutput:
    call_id: str
    output: str

    def serialize(self) -> dict:
        return {
            "type": "function_call_output",
            "call_id": self.call_id,
            "output": self.output
        }

@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict
    call_id: str

    def execute(self, tools: Tools) -> ToolOutput:
        if self.name not in tools.mapping:
            output = {
                "status": "error",
                "message": f"tool {self.name} not found",
            }
        else:
            output = tools.mapping[self.name](**self.args)

        return ToolOutput(
            call_id=self.call_id,
            output=json.dumps(output),
        )