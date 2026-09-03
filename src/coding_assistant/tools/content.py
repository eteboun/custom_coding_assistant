import subprocess
import ast
import inspect
import json

from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass
from pydantic import ValidationError

from .schemas import Symbol, SymbolKind, ToolSchema
from .utils import (symbol_matches, parse_python_file,
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
                "Replace one or more exact pieces of content in a single existing file. "
                "Each replacement is searched only within its specified original line range "
                "and its old_text must occur exactly once within that range. "
                "Replacement matches must not overlap. "
                "All line ranges refer to the file state before any replacement is applied. "
                "Use multiple replacement entries when making independent edits to the same file. "
                "A successful result confirms that all replacements were applied; "
                "do not re-read the file solely to verify them."
        ),
        property_descriptions={
            "path": (
                    "Repository-relative path of the existing file to modify."
            ),
            "replacements": (
                    "List of replacements to apply to the file. "
                    "Each item contains start_line, end_line, old_text, and new_text. "
                    "start_line and end_line are optional 1-based line bounds referring to "
                    "the original file content. old_text must match exactly once within that "
                    "range, and new_text is the content that replaces it."
            ),
        },
        additional_properties=False,
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

        def _validate_replacements() -> OutputProtocol:

            def _set_old_text_ranges(
                    replacement_objs_: list[Replacement]
            ) -> list[Replacement]:

                for replacement_ in replacement_objs_:
                    start_ = (
                        replacement_.start_line - 1
                        if replacement_.start_line is not None
                        else 0
                    )
                    end_ = (
                        replacement_.end_line
                        if replacement_.end_line is not None
                        else len(lines)
                    )

                    target_piece_ = "".join(lines[start_:end_])

                    replacement_.old_text_start = (
                            line_offsets[start_]
                            + target_piece_.find(replacement_.old_text)
                    )
                    replacement_.old_text_end = (replacement_.old_text_start
                                                 + len(replacement_.old_text))

                return replacement_objs_

            def _validate_params(
                    replacements_: list[dict]
            ) -> OutputProtocol:

                errors_ = []
                replacement_objs_ = []

                for idx, replacement_ in enumerate(replacements_):

                    try:
                        replacement_obj_ = Replacement(**replacement_)

                    except ValidationError as e:
                        errors_.append({
                            "index": idx,
                            "message": e.errors()
                        })
                        continue

                    temp_start = (
                        replacement_obj_.start_line
                        if replacement_obj_.start_line is not None
                        else 0
                    )

                    temp_end = (
                        replacement_obj_.end_line
                        if replacement_obj_.end_line is not None
                        else len(lines)
                    )

                    if temp_start > temp_end:
                        errors_.append({
                            "index": idx,
                            "message": "Start line can not be greater than end line"
                        })

                    else:
                        replacement_objs_.append(
                            replacement_obj_
                        )

                if len(errors_) > 0:
                    return OutputProtocol(
                        status=Status.ERROR,
                        content=errors_,
                        message="Replacements fail to satisfy parameter requirements"
                    )

                return OutputProtocol(
                    status=Status.SUCCESS,
                    content=replacement_objs_
                )

            def _validate_counts(
                    replacement_objs_: list[Replacement]
            ) -> OutputProtocol:

                errors_: list[dict] = []

                for idx, replacement_ in enumerate(replacement_objs_):

                    start_ = (
                        replacement_.start_line - 1
                        if replacement_.start_line is not None
                        else 0
                    )
                    end_ = (
                        replacement_.end_line
                        if replacement_.end_line is not None
                        else len(lines)
                    )

                    target_piece_ = "".join(lines[start_:end_])

                    count = target_piece_.count(replacement_.old_text)

                    if count == 0:
                        errors_.append({
                            "index": idx,
                            "message": f"No match found for {replacement_.old_text} in {path}"
                        })

                    elif count > 1:
                        errors_.append({
                            "index": idx,
                            "message": f"Multiple matches found for {replacement_.old_text} in {path}"
                        })

                if len(errors_) > 0:
                    return OutputProtocol(
                        status=Status.ERROR,
                        content=errors_,
                        message="Replacements fail to satisfy count requirements"
                    )

                return OutputProtocol(
                    status=Status.SUCCESS,
                    content=replacement_objs_
                )

            def _validate_ranges(
                    replacement_objs_: list[Replacement]
            ) -> OutputProtocol:

                errors_: list[dict] = []

                replacement_ranges: dict[int, tuple[int, int]] = {}

                for idx, replacement_ in enumerate(replacement_objs_):

                    for idx_, (other_start, other_end) in replacement_ranges.items():
                        if (
                                replacement_.old_text_start < other_end
                                and other_start < replacement_.old_text_end
                        ):
                            errors_.append({
                                "message": f"Replacements {idx} and {idx_} conflict."
                            })

                    replacement_ranges[idx] = (
                        replacement_.old_text_start,
                        replacement_.old_text_end,
                    )

                if len(errors_) > 0:
                    return OutputProtocol(
                        status=Status.ERROR,
                        content=errors_,
                        message="Replacements fail to satisfy range requirements"
                    )

                return OutputProtocol(
                    status=Status.SUCCESS,
                    content=replacement_objs_
                )

            validated_replacements_ = _validate_params(
                replacements_=replacements
            )

            if validated_replacements_.is_fail():
                return validated_replacements_

            validated_replacements_ = _validate_counts(
                replacement_objs_=validated_replacements_.content
            )

            if validated_replacements_.is_fail():
                return validated_replacements_

            replacement_objs = _set_old_text_ranges(
                replacement_objs_=validated_replacements_.content
            )

            return _validate_ranges(
                replacement_objs_=replacement_objs
            )

        validated_replacements = _validate_replacements()

        if validated_replacements.is_fail():
            return validated_replacements

        replacement_order = list(sorted(
            validated_replacements.content,
            key=lambda r: r.old_text_start,
            reverse=True
        ))

        text = "".join(lines)

        for replacement in replacement_order:
            assert replacement.old_text_start is not None
            assert replacement.old_text_end is not None

            text = (
                    text[:replacement.old_text_start]
                    + replacement.new_text
                    + text[replacement.old_text_end:]
            )

        with open(full_path, "w", encoding="utf-8") as file:
            file.write(text)

        return OutputProtocol(
            status=Status.SUCCESS,
            content=path,
        )

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
        tool_description="Deletes the file with provided path.",
        property_descriptions={
            "path": "Repository-relative path for the file to be deleted.",
        },
        additional_properties=False
    )
    def delete_file(self, path: str) -> OutputProtocol:
        resolved_path = self.pather.resolve_path(path=path)

        if resolved_path.is_fail():
            return resolved_path

        full_path = resolved_path.content

        full_path.unlink()

        return OutputProtocol(
            status=Status.SUCCESS,
            content=path
        )

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
    def run_command(self, command: list[str]) -> OutputProtocol:
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

    @_tool(
        tool_description="Run a Python script.",
        property_descriptions={
            "path": "Repository-relative file path."
        },
        additional_properties=False,
    )
    def run_python_file(self, path: str) -> OutputProtocol:

        resolved_file = self.pather.resolve_file(path=path)

        if resolved_file.is_fail():
            return resolved_file

        full_path = resolved_file.content

        if full_path.suffix != ".py":
            return OutputProtocol(
                status=Status.ERROR,
                message=f"File {full_path} is not a Python file"
            )

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
    def run_python_code(self, code: str) -> OutputProtocol:
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