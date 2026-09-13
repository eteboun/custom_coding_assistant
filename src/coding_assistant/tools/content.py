import subprocess
import ast
import inspect

from collections.abc import Callable
from pathlib import Path
from dataclasses import dataclass

from .schemas import Symbol, SymbolKind, ToolSchema, Parameters
from .utils import symbol_matches, FilePatch, Hunk, Pather
from ..utils import OutputProtocol

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
                status="error",
                message="Execution timed out",
            )
        except FileNotFoundError:
            return OutputProtocol(
                status="error",
                message="Docker is not installed or not in PATH",
            )

        return OutputProtocol(
            status="success" if completed.returncode == 0 else "error",
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

    def _tools(self):
        funcs = []

        for _, func in inspect.getmembers(self, predicate=inspect.ismethod):
            if getattr(func, "is_tool", False):
                funcs.append(func)

        return funcs

    def _tool_mapping(self) -> dict[str, Callable]:
        tools = self._tools()
        return {
            tool.__name__: tool
            for tool in tools
        }

    def _tool_datas(self) -> list[ToolSchema]:
        tools = self._tools()
        return [
            tool.tool_data
            for tool in tools
        ]

    def tools(self) -> list[str]:
        return [
            tool.__name__
            for tool in self._tools()
        ]

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
            status="success",
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
    def list_directory(self, path: str) -> OutputProtocol:
        resolved_dir = self.pather.resolve_dir(path=path)

        if resolved_dir.is_fail():
            return resolved_dir

        entries = sorted(
            e.name
            for e in resolved_dir.content.iterdir()
            if self.pather.is_allowed_path(e)
        )

        return OutputProtocol(
            status="success",
            content=entries,
        )

    @_tool(
        description=(
                "Find repository files whose paths match an optional glob pattern. "
                "If no pattern is provided, list repository files. "
                "Use this when relevant files are unknown but can be narrowed by path, filename, or extension."
        ),
        parameters=Parameters(
            properties={
                "pattern": {
                    "type": "string",
                    "description": (
                            "Optional glob pattern such as '*.py', "
                            "'src/**/*.ts', or '**/*test*'."
                    ),
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of matching paths to return.",
                    "minimum": 1,
                    "default": 100,
                },
            },
            required=[],
            additional_properties=False,
        ),
    )
    def search_files(
            self,
            pattern: str | None = None,
            max_results: int = 100,
    ) -> OutputProtocol:
        return self.pather.search_files(
            pattern=pattern,
            max_results=max_results
        )

    @_tool(
        description="Search repository contents for text or regex matches.",
        parameters=Parameters(
            properties={
                "query": {
                    "type": "string",
                    "description": "Text or regular expression to search for.",
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Surrounding lines per match.",
                },
                "max_output_lines": {
                    "type": "integer",
                    "description": "Maximum output lines.",
                }
            },
            required=["query"],
            additional_properties=False,
        )
    )
    def search_code(self,
                    query: str,
                    context_lines: int = 2,
                    max_output_lines: int = 100
                    ) -> OutputProtocol:
        try:
            command = [
                "rg",
                "-n",
                "-C",
                str(context_lines),
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
                status="error",
                message="ripgrep is not installed or not available in PATH"
            )

        if process.returncode == 0:
            findings = process.stdout.splitlines()

            return OutputProtocol(
                status="success",
                content="\n".join(findings[:max_output_lines])
            )

        elif process.returncode == 1:
            return OutputProtocol(
                status="error",
                message="No match found"
            )

        else:
            return OutputProtocol(
                status="error",
                message=f"An error occurred: {process.stderr}"
            )

    @_tool(
        description=(
                "Apply a Codex-style patch containing one or more file operations. "
                "Supported file operations are only: "
                "'*** Update File: <path>', "
                "'*** Add File: <path>', and "
                "'*** Delete File: <path>'. "
                "The patch must start with '*** Begin Patch' and end with '*** End Patch'. "
                "Update File operations may contain one or more hunks separated by '@@'. "
                "Within update hunks, lines prefixed with ' ' are unchanged context, "
                "'-' lines are removed, and '+' lines are added. "
                "Update hunks are matched against the original file state, must match exactly once, "
                "and must not overlap. "
                "Use only enough unchanged context to identify each target uniquely. "
                "Add File content must consist only of '+' prefixed lines. "
                "Delete File operations must not contain file content. "
                "Unsupported operations or metadata must not be used."
        ),
        parameters=Parameters(
            properties={
                "patch": {
                    "type": "string",
                    "description": (
                            "Complete patch in Codex-style format. "
                            "Supported structure:\n"
                            "*** Begin Patch\n"
                            "*** Update File: <path>\n"
                            "@@\n"
                            " <unchanged context>\n"
                            "-<removed line>\n"
                            "+<added line>\n"
                            "@@\n"
                            " <another hunk>\n"
                            "*** Add File: <path>\n"
                            "+<new file content>\n"
                            "*** Delete File: <path>\n"
                            "*** End Patch\n"
                            "Supported Update File hunks are '@@'-separated contiguous edit regions "
                            "using only ' ', '-', and '+' line prefixes."
                    ),
                },
            },
            required=["patch"],
            additional_properties=False,
        ),
        strict=True,
    )
    def apply_patch(
            self,
            patch: str,
    ) -> OutputProtocol:
        patch = patch.replace("\r\n", "\n").replace("\r", "\n")

        try:
            file_patches = self._parse_patch(patch)
        except ValueError as e:
            return OutputProtocol(
                status="error",
                message=str(e),
            )

        pending_writes: dict[Path, str] = {}
        pending_deletes: set[Path] = set()

        for file_patch in file_patches:
            if file_patch.operation == "update":
                resolved = self.pather.resolve_file(file_patch.path)

                if resolved.is_fail():
                    return resolved

                full_path = resolved.content

                with open(full_path, "r", encoding="utf-8", newline="") as f:
                    initial_content = f.read()

                try:
                    new_content = self._apply_update(
                        initial_content,
                        file_patch.lines,
                    )
                except ValueError as e:
                    return OutputProtocol(
                        status="error",
                        message=f"{file_patch.path}: {e}",
                    )

                pending_writes[full_path] = new_content

            elif file_patch.operation == "delete":
                resolved = self.pather.resolve_file(file_patch.path)

                if resolved.is_fail():
                    return resolved

                full_path = resolved.content

                if file_patch.lines:
                    return OutputProtocol(
                        status="error",
                        message=(
                            f"{file_patch.path}: Delete File "
                            "must not contain patch content."
                        ),
                    )

                pending_deletes.add(full_path)

            elif file_patch.operation == "add":
                resolved = self.pather.resolve_path(file_patch.path)

                if resolved.is_fail():
                    return resolved

                full_path = resolved.content

                if full_path.exists():
                    return OutputProtocol(
                        status="error",
                        message=f"{file_patch.path}: File already exists.",
                    )

                try:
                    new_content = self._parse_added_file(
                        file_patch.lines
                    )
                except ValueError as e:
                    return OutputProtocol(
                        status="error",
                        message=f"{file_patch.path}: {e}",
                    )

                pending_writes[full_path] = new_content

        if pending_deletes & pending_writes.keys():
            return OutputProtocol(
                status="error",
                message="A file cannot be both written and deleted.",
            )

        for path in pending_deletes:
            path.unlink()

        for path, content in pending_writes.items():
            path.parent.mkdir(parents=True, exist_ok=True)

            with open(
                    path,
                    "w",
                    encoding="utf-8",
                    newline="",
            ) as f:
                f.write(content)

        return OutputProtocol(
            status="success",
            content="Successfully applied patch.",
        )

    @staticmethod
    def _parse_patch(patch: str) -> list[FilePatch]:
        lines = patch.split("\n")

        if not lines or lines[0] != "*** Begin Patch":
            raise ValueError("Patch must start with '*** Begin Patch'.")

        if lines[-1] != "*** End Patch":
            raise ValueError("Patch must end with '*** End Patch'.")

        result: list[FilePatch] = []
        current: FilePatch | None = None

        for line in lines[1:-1]:
            if line.startswith("*** Update File: "):
                if current is not None:
                    result.append(current)

                current = FilePatch(
                    operation="update",
                    path=line.removeprefix("*** Update File: ").strip(),
                    lines=[],
                )

            elif line.startswith("*** Add File: "):
                if current is not None:
                    result.append(current)

                current = FilePatch(
                    operation="add",
                    path=line.removeprefix("*** Add File: ").strip(),
                    lines=[],
                )

            elif line.startswith("*** Delete File: "):
                if current is not None:
                    result.append(current)

                current = FilePatch(
                    operation="delete",
                    path=line.removeprefix("*** Delete File: ").strip(),
                    lines=[],
                )

            elif line.startswith("*** "):
                raise ValueError(
                    f"Unsupported patch metadata: {line}"
                )

            else:
                if current is None:
                    if not line:
                        continue

                    raise ValueError(
                        "Patch content appears before a file operation."
                    )

                current.lines.append(line)

        if current is not None:
            result.append(current)

        if not result:
            raise ValueError("Patch contains no file operations.")

        paths = [file_patch.path for file_patch in result]

        if len(paths) != len(set(paths)):
            raise ValueError(
                "Each file may appear only once in a patch."
            )

        return result

    @staticmethod
    def _apply_update(
            initial_content: str,
            lines: list[str],
    ) -> str:
        newline = "\r\n" if "\r\n" in initial_content else "\n"

        raw_hunks: list[list[str]] = []
        current: list[str] = []

        for line in lines:
            if line.startswith("@@"):
                if current:
                    raw_hunks.append(current)
                    current = []
                continue

            if line == "*** End of File":
                continue

            if not line.startswith((" ", "-", "+")):
                if not line:
                    continue

                raise ValueError(
                    f"Invalid patch line: {line!r}"
                )

            current.append(line)

        if current:
            raw_hunks.append(current)

        if not raw_hunks:
            raise ValueError("Update contains no hunks.")

        hunks: list[Hunk] = []

        for index, raw_hunk in enumerate(raw_hunks):
            old_lines = [
                line[1:]
                for line in raw_hunk
                if line.startswith((" ", "-"))
            ]

            new_lines = [
                line[1:]
                for line in raw_hunk
                if line.startswith((" ", "+"))
            ]

            if not old_lines:
                raise ValueError(
                    f"Hunk {index} contains no existing text."
                )

            old_text = newline.join(old_lines)
            new_text = newline.join(new_lines)

            first = initial_content.find(old_text)

            if first == -1:
                raise ValueError(
                    f"Hunk {index} target was not found."
                )

            second = initial_content.find(
                old_text,
                first + 1,
            )

            if second != -1:
                raise ValueError(
                    f"Hunk {index} target is ambiguous."
                )

            hunks.append(
                Hunk(
                    start=first,
                    end=first + len(old_text),
                    new_text=new_text,
                )
            )

        hunks.sort(key=lambda hunk: hunk.start)

        for current_, next_hunk in zip(hunks, hunks[1:]):
            if next_hunk.start < current_.end:
                raise ValueError("Update hunks overlap.")

        content = initial_content

        for hunk in reversed(hunks):
            content = (
                    content[:hunk.start]
                    + hunk.new_text
                    + content[hunk.end:]
            )

        return content

    @staticmethod
    def _parse_added_file(lines: list[str]) -> str:
        content: list[str] = []

        for line in lines:
            if not line:
                continue

            if not line.startswith("+"):
                raise ValueError(
                    "Every Add File content line must start with '+'."
                )

            content.append(line[1:])

        return "\n".join(content)

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
                status="error",
                message=str(e),
            )

        return OutputProtocol(
            status="success",
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
                status="error",
                message=f"Tool {self.name} not found"
            )
        else:
            output = tools.mapping[self.name](**self.args)

        return ToolOutput(
            name=self.name,
            call_id=self.call_id,
            output=output
        )