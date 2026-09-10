import subprocess
import ast
import inspect

from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass

from .schemas import Symbol, SymbolKind, ToolSchema, Parameters
from .utils import (symbol_matches, parse_python_file, _strip_final_newline,
                    Pather, OutputProtocol, Status, Replacement)

class Tools:

    def __init__(self,
                 repo_path: Path,
                 blocked_files: list[str],
                 blocked_dirs: list[str]
                 ) -> None:

        self.pather = Pather(
            repo_path=repo_path,
            blocked_files=blocked_files,
            blocked_dirs=blocked_dirs
        )
        self.repo_path = repo_path

        self.mapping = self._tool_mapping()
        self.datas = self._tool_datas()

    def _run_docker(self, command: list[str]) -> OutputProtocol:
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
            return OutputProtocol(
                status=Status.ERROR,
                message="Execution timed out",
            )
        except FileNotFoundError:
            return OutputProtocol(
                status=Status.ERROR,
                message="Docker is not installed or not in PATH",
            )

        return OutputProtocol(
            status=Status.SUCCESS if completed.returncode == 0 else Status.ERROR,
            content={
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "returncode": completed.returncode,
            },
            message="Execution failed" if completed.returncode != 0 else None,
        )

    def _run_dockerized_file(self, path: Path) -> OutputProtocol:
        relative_path = path.relative_to(self.repo_path)

        return self._run_docker([
            "python",
            relative_path.as_posix(),
        ])

    def _run_dockerized_code(self, code: str) -> OutputProtocol:
        return self._run_docker([
            "python",
            "-c",
            code,
        ])

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

                if symbol_matches(
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

                if symbol_matches(
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

    def _tool_mapping(self) -> dict[str, Callable]:

        return {
            func.__name__: func
            for _, func in inspect.getmembers(self, predicate=inspect.ismethod)
            if getattr(func, "is_tool", False)
        }

    def _tool_datas(self) -> list[ToolSchema]:

        return [
            func.tool_data
            for _, func in inspect.getmembers(self, predicate=inspect.ismethod)
            if getattr(func, "is_tool", False)
        ]

    @staticmethod
    def _tool(
            description: str,
            parameters: Parameters,
            strict: bool = False
    ) -> Callable:

        def decorator(func):

            tool_data = ToolSchema.from_func(
                func=func,
                description=description,
                parameters=parameters,
                strict=strict
            )

            func.is_tool = True
            func.tool_data = tool_data

            return func

        return decorator

    @_tool(
        description=(
                "Read a known text file, optionally within a line range. "
        ),
        parameters=Parameters(
            properties={
                "path": {
                    "type": "string",
                    "description": "Repository-relative file path.",
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional 1-based starting line.",
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Optional 1-based ending line, inclusive.",
                }
            },
            required=["path", "start_line", "end_line"],
            additional_properties=False
        )
    )
    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> OutputProtocol:
        resolved_file = self.pather.resolve_file(path=path)

        if resolved_file.is_fail():
            return resolved_file

        full_path = resolved_file.content

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

        return OutputProtocol(
            status=Status.SUCCESS,
            content="".join(numbered_lines)
        )

    @_tool(
        description=(
                "List files and directories inside a known repository directory."
        ),
        parameters=Parameters(
            properties={
                "path": {
                    "type": "string",
                    "description": "Repository-relative directory path. Use '.' for the root.",
                }
            },
            required=["path"],
            additional_properties=False,
        ),
    )
    def list_files(self, path: str) -> OutputProtocol:
        resolved_dir = self.pather.resolve_dir(path=path)

        if resolved_dir.is_fail():
            return resolved_dir

        full_path = resolved_dir.content

        return OutputProtocol(
            status=Status.SUCCESS,
            content=[
                e.name
                for e in full_path.iterdir()
            ]
        )

    @_tool(
        description=(
                "Search repository python files "
                "for specific class or function names when the location is unknown."
        ),
        parameters=Parameters(
            properties={
                "notation": {
                    "type": "string",
                    "description": (
                            "Class or function name with proper hierarchy. "
                            "E.g. 'run' for general search for the function 'run', "
                            "'Assistant.run' for the method 'run' in the 'Assistant' class."
                    ),
                }
            },
            required=["notation"],
            additional_properties=False,
        ),
    )
    def search_symbol(self, notation: str) -> OutputProtocol:

        full_paths = self.pather.search_files_containing_terms(
            notation.split("."),
            extension=".py"
        )

        symbols: list[dict] = []
        errors: list[str] = []

        allow_unqualified = "." not in notation
        for full_path in full_paths:

            try:
                tree = parse_python_file(path=full_path)
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

        content = {
            "symbols": symbols
        }

        if errors:
            content["errors"] = errors

        return OutputProtocol(
            status=Status.SUCCESS,
            content=content
        )

    @_tool(
        description=(
                "Read a specific class or function data "
                "when both its file path and exact qualified name are known."
        ),
        parameters=Parameters(
            properties={
                "path": {
                    "type": "string",
                    "description": "Repository-relative Python file path.",
                },
                "notation": {
                    "type": "string",
                    "description": (
                            "Class or function name with proper hierarchy. "
                            "E.g. 'run' for general search for the function 'run', "
                            "'Assistant.run' for the method 'run' in the 'Assistant' class."
                    ),
                },
            },
            required=["path", "notation"],
            additional_properties=False,
        ),
    )
    def read_symbol(self, path: str, notation: str) -> OutputProtocol:

        resolved_file = self.pather.resolve_file(path=path)

        if resolved_file.is_fail():
            return resolved_file

        full_path = resolved_file.content

        try:
            tree = parse_python_file(path=full_path)
        except SyntaxError:
            return OutputProtocol(
                status=Status.ERROR,
                message=f"Failed to parse Python file: {
                    full_path.relative_to(self.repo_path).as_posix()
                }"
            )

        symbols = self._walk_symbols(
            search_notation=notation,
            allow_unqualified=False,
            path=full_path.relative_to(self.repo_path),
            node=tree
        )

        if not symbols:
            return OutputProtocol(
                status=Status.ERROR,
                message=f"Symbol not found: {notation}"
            )

        if len(symbols) > 1:
            return OutputProtocol(
                status=Status.ERROR,
                message=f"Multiple symbols found: {notation}"
            )

        symbol_data = symbols[0]

        read_result = Tools.read_file(
            path=path,
            start_line=symbol_data.start_line,
            end_line=symbol_data.end_line
        )

        if read_result.is_fail():
            return read_result

        return OutputProtocol(
            status=Status.SUCCESS,
            content={
                "notation": symbol_data.notation,
                "content": read_result.content
            }
        )

    @_tool(
        description=(
                "Search repository contents for text or regex matches."
        ),
        parameters=Parameters(
            properties={
                "query": {
                    "type": "string",
                    "description": "Text or regular expression to search for.",
                }
            },
            required=["query"],
            additional_properties=False,
        ),
    )
    def search_code(self, query: str) -> OutputProtocol:
        try:
            command = [
                "rg",
                "-n",
                query,
                self.repo_path.as_posix(),
            ]

            for file in self.pather.blocked_files:
                command.extend(["-g", f"!{file}"])

            for directory in self.pather.blocked_dirs:
                command.extend(["-g", f"!{directory}/**"])

            process = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace"
            )
        except FileNotFoundError:
            return OutputProtocol(
                status=Status.ERROR,
                message="ripgrep is not installed or not available in PATH"
            )

        if process.returncode == 0:
            return OutputProtocol(
                status=Status.SUCCESS,
                content=process.stdout
            )

        elif process.returncode == 1:
            return OutputProtocol(
                status=Status.ERROR,
                message="No match found"
            )

        else:
            return OutputProtocol(
                status=Status.ERROR,
                message=f"An error occurred: {process.stderr}"
            )

    @_tool(
        description=(
                "Replace one or more exact line ranges in a single existing file. "
                "All ranges are inclusive, 1-based, and refer to the original file state. "
                "old_text must exactly match the selected range, and ranges must not overlap. "
                "Use the smallest line range that contains the required change. "
                "Do not include unchanged surrounding lines. "
                "Batch independent edits to the same file into one call."
        ),
        parameters=Parameters(
            properties={
                "path": {
                    "type": "string",
                    "description": (
                            "Repository-relative path of the existing file to modify."
                    ),
                },
                "replacements": {
                    "type": "array",
                    "description": (
                            "List of replacements to apply. "
                            "Each replacement selects an inclusive 1-based line range."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "start_line": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "First line of the range.",
                            },
                            "end_line": {
                                "type": "integer",
                                "minimum": 1,
                                "description": "Last line of the range, inclusive.",
                            },
                            "old_text": {
                                "type": "string",
                                "description": (
                                        "Exact content of the selected line range."
                                ),
                            },
                            "new_text": {
                                "type": "string",
                                "description": (
                                        "Content that replaces the selected line range."
                                ),
                            },
                        },
                        "required": [
                            "start_line",
                            "end_line",
                            "old_text",
                            "new_text",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            required=["path", "replacements"],
            additional_properties=False,
        ),
        strict=True
    )
    def replace_in_file(
        self,
        path: str,
        replacements: list[dict]
    ) -> OutputProtocol:

        if not replacements:
            return OutputProtocol(
                status=Status.ERROR,
                message="At least one replacement is required",
            )

        resolved_file = self.pather.resolve_file(path=path)

        if resolved_file.is_fail():
            return resolved_file

        full_path = resolved_file.content
        with open(full_path, "r", encoding="utf-8") as file:
            lines = file.readlines()

        line_offsets = [0]

        for line in lines:
            line_offsets.append(line_offsets[-1] + len(line))

        def _validate_replacements(replacement_objs_: list[Replacement]) -> OutputProtocol:

            def _validate_ranges() -> OutputProtocol:

                errors_: list[dict] = []

                replacement_ranges: dict[int, tuple[int, int]] = {}

                for idx, replacement_ in enumerate(replacement_objs_):
                    if (
                            replacement_.start_line
                            > replacement_.end_line
                    ):
                        errors_.append({
                            "index": idx,
                            "message": "Start line can not be greater than end line"
                        })
                        continue

                    if replacement_.end_line > len(lines):
                        errors_.append({
                            "index": idx,
                            "message": "Out of bounds line range"
                        })
                        continue

                    for idx_, (other_start, other_end) in replacement_ranges.items():
                        if (
                                replacement_.start_line <= other_end
                                and other_start <= replacement_.end_line
                        ):
                            errors_.append({
                                "message": f"Replacements {idx} and {idx_} conflict"
                            })

                    replacement_ranges[idx] = (
                        replacement_.start_line,
                        replacement_.end_line,
                    )

                if len(errors_) > 0:
                    return OutputProtocol(
                        status=Status.ERROR,
                        content=errors_,
                        message="Replacements do not match the specified line ranges"
                    )

                return OutputProtocol(
                    status=Status.SUCCESS,
                    content=replacement_objs_
                )

            def _validate_old_texts() -> OutputProtocol:

                errors_: list[dict] = []

                for idx, replacement_ in enumerate(replacement_objs_):

                    start_ = replacement_.start_line - 1
                    end_ = replacement_.end_line

                    target_piece_ = "".join(lines[start_:end_])

                    if (
                            _strip_final_newline(target_piece_)
                            != _strip_final_newline(replacement_.old_text)
                    ):
                        errors_.append({
                            "index": idx,
                            "message": "Provided lines do not match old text"
                        })

                if len(errors_) > 0:
                    return OutputProtocol(
                        status=Status.ERROR,
                        content=errors_,
                        message="Replacements do not match the specified line ranges"
                    )

                return OutputProtocol(
                    status=Status.SUCCESS,
                    content=replacement_objs_
                )

            validated_replacements_ = _validate_ranges()

            if validated_replacements_.is_fail():
                return validated_replacements_

            return _validate_old_texts()

        replacement_objs = [
            Replacement.model_construct(**replacement)
            for replacement in replacements
        ]

        validated_replacements = _validate_replacements(
            replacement_objs_=replacement_objs
        )

        if validated_replacements.is_fail():
            return validated_replacements

        replacement_order = sorted(
            validated_replacements.content,
            key=lambda r: r.start_line,
            reverse=True
        )

        text = "".join(lines)

        for replacement in replacement_order:
            start = line_offsets[replacement.start_line - 1]
            end = line_offsets[replacement.end_line]

            old_piece = text[start:end]
            has_trailing_newline = old_piece.endswith("\n")

            new_text = replacement.new_text
            if has_trailing_newline and new_text:
                new_text += "\n"

            text = text[:start] + new_text + text[end:]

        with open(full_path, "w", encoding="utf-8") as file:
            file.write(text)

        return OutputProtocol(
            status=Status.SUCCESS,
            content=path,
        )

    @_tool(
        description=(
                "Create a new file."
        ),
        parameters=Parameters(
            properties={
                "path": {
                    "type": "string",
                    "description": "Repository-relative path for the new file.",
                },
                "content": {
                    "type": "string",
                    "description": "Complete initial content of the file.",
                },
            },
            required=["path", "content"],
            additional_properties=False,
        ),
    )
    def create_file(
        self,
        path: str,
        content: str,
    ) -> OutputProtocol:
        resolved_path = self.pather.resolve_path(path=path)

        if resolved_path.is_fail():
            return resolved_path

        full_path = resolved_path.content

        if full_path.exists():
            return OutputProtocol(
                status=Status.ERROR,
                message=f"File {full_path} already exists",
            )

        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")

        return OutputProtocol(
            status=Status.SUCCESS,
            content={
                "path": path,
            }
        )

    @_tool(
        description="Deletes the file with provided path.",
        parameters=Parameters(
            properties={
                "path": {
                    "type": "string",
                    "description": "Repository-relative path for the file to be deleted.",
                },
            },
            required=["path"],
            additional_properties=False,
        ),
    )
    def delete_file(self, path: str) -> OutputProtocol:
        resolve_filed = self.pather.resolve_file(path=path)

        if resolve_filed.is_fail():
            return resolve_filed

        full_path = resolve_filed.content

        full_path.unlink()

        return OutputProtocol(
            status=Status.SUCCESS,
            content=path
        )

    @_tool(
        description="Deletes the directory with provided path.",
        parameters=Parameters(
            properties={
                "path": {
                    "type": "string",
                    "description": "Repository-relative path for the directory to be deleted.",
                },
            },
            required=["path"],
            additional_properties=False,
        ),
    )
    def delete_dir(self, path: str) -> OutputProtocol:
        resolved_dir = self.pather.resolve_dir(path=path)

        if resolved_dir.is_fail():
            return resolved_dir

        full_path = resolved_dir.content

        try:
            full_path.rmdir()
        except OSError as e:
            return OutputProtocol(
                status=Status.ERROR,
                message=str(e),
            )

        return OutputProtocol(
            status=Status.SUCCESS,
            content=path,
        )

    @_tool(
        description=(
                "Runs a command in an isolated Docker container "
                "with the repository as the working directory."
        ),
        parameters=Parameters(
            properties={
                "command": {
                    "type": "array",
                    "items": {
                        "type": "string",
                    },
                    "description": (
                            "Command and arguments to execute, provided as a list. "
                            "Example: ['python', '-m', 'pytest']."
                    ),
                },
            },
            required=["command"],
            additional_properties=False,
        ),
    )
    def run_command(self, command: list[str]) -> OutputProtocol:
        return self._run_docker(
            command=command
        )

    @_tool(
        description=(
                "Show the repository structure for broad exploration when relevant files are unknown."
        ),
        parameters=Parameters(
            properties={},
            required=[],
            additional_properties=False,
        ),
    )
    def repo_tree(self) -> OutputProtocol:
        files: list[str] = []

        for path in self.repo_path.rglob("*"):
            relative_path = path.relative_to(self.repo_path)

            if self.pather.is_allowed_filepath(path=path):
                files.append(relative_path.as_posix())

        return OutputProtocol(
            status=Status.SUCCESS,
            content=files,
        )

@dataclass(frozen=True)
class ToolOutput:
    name: str
    call_id: str
    output: OutputProtocol

@dataclass(frozen=True)
class ToolCall:
    name: str
    args: dict
    call_id: str

    def execute(self, tools: Tools) -> ToolOutput:
        if self.name not in tools.mapping:
            output = OutputProtocol(
                status=Status.ERROR,
                message=f"Tool {self.name} not found"
            )
        else:
            output = tools.mapping[self.name](**self.args)

        return ToolOutput(
            name=self.name,
            call_id=self.call_id,
            output=output
        )