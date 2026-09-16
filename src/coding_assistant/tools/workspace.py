import subprocess
import json
from pathlib import Path
from typing import ClassVar, Literal
from dataclasses import dataclass, field

from ..utils import OutputProtocol, ToolUsageError, ToolEnvironmentError

Operation = Literal["update", "add", "delete"]

@dataclass(frozen=True)
class FilePatch:
    operation: Operation
    path: str
    lines: list[str]

@dataclass(frozen=True)
class Hunk:
    start: int
    end: int
    new_text: str

@dataclass(frozen=True)
class PathOperation:
    output: OutputProtocol
    files: tuple[str, ...] = field(default_factory=tuple)


class Workspace:

    REPO_TREE_MAX_DEPTH: ClassVar[int] = 4

    def __init__(self,
                 repo_path: Path,
                 blocked_files: list[str],
                 blocked_dirs: list[str]
                 ) -> None:

        self.repo_path = repo_path
        self.blocked_files = blocked_files
        self.blocked_dirs = blocked_dirs

    @staticmethod
    def _run_ripgrep(
            cmd: list[str],
            cwd: Path
    ):
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True
            )

        except FileNotFoundError as e:
            raise ToolEnvironmentError(
                "ripgrep is not installed or not available in PATH"
            ) from e

        if result.returncode not in (0, 1):
            raise ToolEnvironmentError(
                f"ripgrep failed: {result.stderr.strip()}"
            )

        return result

    def _resolve_path(
            self,
            path: str,
    ) -> OutputProtocol:
        full_path = (self.repo_path / path).resolve()

        if not full_path.is_relative_to(self.repo_path):
            raise ToolUsageError(
                "Access outside the repository is denied"
            )

        if full_path.name in self.blocked_files:
            raise ToolUsageError(
                "Path is not accessible"
            )

        relative_parts = full_path.relative_to(self.repo_path).parts

        if any(part in self.blocked_dirs for part in relative_parts):
            raise ToolUsageError(
                "Path is not accessible"
            )

        return OutputProtocol(
            status="success",
            content=full_path
        )

    def _resolve_dir(
            self,
            path: str
    ) -> OutputProtocol:

        resolved_path = self._resolve_path(
            path=path
        )
        full_path = resolved_path.content

        if not full_path.exists():
            raise ToolUsageError(
                f"Directory {path} does not exist"
            )

        if not full_path.is_dir():
            raise ToolUsageError(
                f"{path} is not a directory"
            )

        return OutputProtocol(
            status="success",
            content=full_path,
        )

    def _resolve_file(
            self,
            path: str
    ) -> OutputProtocol:
        resolved_path = self._resolve_path(
            path=path
        )
        full_path = resolved_path.content

        if not full_path.exists():
            raise ToolUsageError(
                f"File {path} does not exist"
            )

        if not full_path.is_file():
            raise ToolUsageError(
                f"{path} is not a file"
            )

        return OutputProtocol(
            status="success",
            content=full_path,
        )

    def _is_allowed_path(
            self,
            path: Path
    ) -> bool:
        try:
            self._resolve_path(
                path=path.as_posix()
            )

        except ToolUsageError:
            return False

        return True

    def _parse_patch(self, patch: str) -> list[FilePatch]:
        lines = patch.split("\n")

        if not lines or lines[0] != "*** Begin Patch":
            raise ToolUsageError("Patch must start with '*** Begin Patch'.")

        if lines[-1] != "*** End Patch":
            raise ToolUsageError("Patch must end with '*** End Patch'.")

        result: list[FilePatch] = []
        current: FilePatch | None = None

        for line in lines[1:-1]:
            if line.startswith("*** Update File: "):
                if current is not None:
                    result.append(current)

                path=Path(
                    line.removeprefix("*** Update File: ").strip(),
                ).relative_to(self.repo_path).as_posix()
                current = FilePatch(
                    operation="update",
                    path=path,
                    lines=[],
                )

            elif line.startswith("*** Add File: "):
                if current is not None:
                    result.append(current)

                path=Path(
                    line.removeprefix("*** Update File: ").strip(),
                ).relative_to(self.repo_path).as_posix()
                current = FilePatch(
                    operation="add",
                    path=path,
                    lines=[],
                )

            elif line.startswith("*** Delete File: "):
                if current is not None:
                    result.append(current)

                path=Path(
                    line.removeprefix("*** Update File: ").strip(),
                ).relative_to(self.repo_path).as_posix()
                current = FilePatch(
                    operation="delete",
                    path=path,
                    lines=[],
                )

            elif line.startswith("*** "):
                raise ToolUsageError(
                    f"Unsupported patch metadata: {line}"
                )

            else:
                if current is None:
                    if not line:
                        continue

                    raise ToolUsageError(
                        "Patch content appears before a file operation."
                    )

                current.lines.append(line)

        if current is not None:
            result.append(current)

        if not result:
            raise ToolUsageError("Patch contains no file operations.")

        paths = [file_patch.path for file_patch in result]

        if len(paths) != len(set(paths)):
            raise ToolUsageError(
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

                raise ToolUsageError(
                    f"Invalid patch line: {line!r}"
                )

            current.append(line)

        if current:
            raw_hunks.append(current)

        if not raw_hunks:
            raise ToolUsageError("Update contains no hunks.")

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
                raise ToolUsageError(
                    f"Hunk {index} contains no existing text."
                )

            old_text = newline.join(old_lines)
            new_text = newline.join(new_lines)

            first = initial_content.find(old_text)

            if first == -1:
                raise ToolUsageError(
                    f"Hunk {index} target was not found."
                )

            second = initial_content.find(
                old_text,
                first + 1,
            )

            if second != -1:
                raise ToolUsageError(
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
                raise ToolUsageError("Update hunks overlap.")

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
                raise ToolUsageError(
                    "Every Add File content line must start with '+'."
                )

            content.append(line[1:])

        return "\n".join(content)

    def search_files(
            self,
            pattern: str | None = None,
            max_results: int = 100
    ) -> PathOperation:
        if max_results < 1:
            raise ToolUsageError(
                "max_results must be at least 1."
            )

        cmd = ["rg", "--files"]

        if pattern:
            cmd += ["-g", pattern]

        for directory in self.blocked_dirs:
            directory = directory.replace("\\", "/").rstrip("/")
            cmd += ["-g", f"!{directory}/**"]

        for file in self.blocked_files:
            file = file.replace("\\", "/")
            cmd += ["-g", f"!{file}"]

        result = self._run_ripgrep(
            cmd=cmd,
            cwd=self.repo_path
        )

        files: list[str] = []

        for raw_path in result.stdout.splitlines():
            path = Path(raw_path)

            if not self._is_allowed_path(path):
                continue

            files.append(path.as_posix())

            if len(files) >= max_results:
                break

        files.sort()

        return PathOperation(
            output=OutputProtocol(
                status="success",
                content=files,
            ),
            files=tuple(files)
        )

    def search_text(
            self,
            text: str,
            context_lines: int = 2,
            max_output_lines: int = 100
    ) -> PathOperation:

        cmd = [
            "rg",
            "--json",
            "-C",
            str(context_lines),
            text,
            self.repo_path.as_posix()
        ]

        for file in self.blocked_files:
            cmd.extend(["-g", f"!{file}"])

        for directory in self.blocked_dirs:
            cmd.extend(["-g", f"!{directory}/**"])

        result = self._run_ripgrep(
            cmd=cmd,
            cwd=self.repo_path,
        )

        if result.returncode == 0:
            files: set[str] = set()
            findings: list[str] = []

            lines = 0
            for line in result.stdout.splitlines():
                event = json.loads(line)

                if event["type"] not in ("match", "context"):
                    continue

                path = Path(event["data"]["path"]["text"])
                line_number = event["data"]["line_number"]
                line_text = event["data"]["lines"]["text"].rstrip("\n")

                if path.is_absolute():
                    path = path.relative_to(self.repo_path)

                path_str = path.as_posix()

                files.add(path_str)
                findings.append(
                    f"{path_str}:{line_number}:{line_text}"
                )

                lines += 1
                if lines >= max_output_lines:
                    break

            return PathOperation(
                output=OutputProtocol(
                    status="success",
                    content="\n".join(findings)
                ),
                files=tuple(sorted(files))
            )

        if result.returncode == 1:
            return PathOperation(
                output=OutputProtocol(
                    status="success",
                    content="No match found"
                )
            )

        raise ToolEnvironmentError(
            f"ripgrep failed: {result.stderr.strip()}"
        )

    def repo_tree(self) -> PathOperation:
        lines: list[str] = []
        files: list[str] = []

        def walk(path: Path, depth: int) -> None:
            if depth > self.REPO_TREE_MAX_DEPTH:
                return

            try:
                entries = sorted(
                    path.iterdir(),
                    key=lambda p: (p.is_file(), p.name.lower()),
                )
            except OSError:
                return

            for entry in entries:
                relative = entry.relative_to(self.repo_path)

                if entry.is_dir():
                    if entry.name in self.blocked_dirs:
                        continue
                elif entry.name in self.blocked_files:
                    continue

                files.append(relative.as_posix())

                indent = "    " * depth

                if entry.is_dir():
                    lines.append(f"{indent}{relative.name}/")
                    walk(entry, depth + 1)
                else:
                    lines.append(f"{indent}{relative.name}")

        walk(self.repo_path, 0)

        files.sort()

        return PathOperation(
            output=OutputProtocol(
                status="success",
                content="\n".join(lines),
            ),
            files=tuple(files)
        )

    def list_directory(self, path: str) -> PathOperation:
        resolved_dir = self._resolve_dir(path=path)

        entries = sorted(
            e.name
            for e in resolved_dir.content.iterdir()
            if self._is_allowed_path(e)
        )

        return PathOperation(
            output=OutputProtocol(
                status="success",
                content=entries
            ),
            files=tuple(entries)
        )

    def delete_dir(self, path: str) -> PathOperation:
        resolved_dir = self._resolve_dir(path=path)
        full_path = resolved_dir.content

        relative_path = full_path.relative_to(
            self.repo_path
        ).as_posix()

        try:
            full_path.rmdir()
        except OSError as e:
            raise ToolUsageError(str(e)) from e

        return PathOperation(
            output=OutputProtocol(
                status="success",
                content=relative_path
            ),
            files=(relative_path,)
        )

    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> PathOperation:
        resolved_file = self._resolve_file(path=path)
        full_path = resolved_file.content

        relative = full_path.relative_to(
            self.repo_path
        ).as_posix()

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

        return PathOperation(
            output=OutputProtocol(
                status="success",
                content="".join(numbered_lines)
            ),
            files=(relative,)
        )

    def apply_patch(
            self,
            patch: str,
    ) -> PathOperation:
        patch = patch.replace("\r\n", "\n").replace("\r", "\n")

        file_patches = self._parse_patch(patch)

        pending_writes: dict[Path, str] = {}
        pending_deletes: set[Path] = set()

        for file_patch in file_patches:
            if file_patch.operation == "update":
                resolved = self._resolve_file(file_patch.path)
                full_path = resolved.content

                with open(full_path, "r", encoding="utf-8", newline="") as f:
                    initial_content = f.read()

                try:
                    new_content = self._apply_update(
                        initial_content,
                        file_patch.lines,
                    )

                except ToolUsageError as e:
                    raise ToolUsageError(
                        f"{file_patch.path}: {e}"
                    ) from e

                pending_writes[full_path] = new_content

            elif file_patch.operation == "delete":
                resolved = self._resolve_file(file_patch.path)
                full_path = resolved.content

                if file_patch.lines:
                    raise ToolUsageError(
                        f"{file_patch.path}: Delete File "
                        "must not contain patch content."
                    )

                pending_deletes.add(full_path)

            elif file_patch.operation == "add":
                resolved = self._resolve_path(file_patch.path)
                full_path = resolved.content

                if full_path.exists():
                    raise ToolUsageError(
                        f"{file_patch.path}: File already exists."
                    )

                try:
                    new_content = self._parse_added_file(
                        file_patch.lines
                    )
                except ValueError as e:
                    raise ToolUsageError(
                        f"{file_patch.path}: {e}"
                    ) from e

                pending_writes[full_path] = new_content

        if pending_deletes & pending_writes.keys():
            raise ToolUsageError(
                "A file cannot be both written and deleted."
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

        files = tuple(sorted({
            Path(patch.path).as_posix()
            for patch in file_patches
        }))

        return PathOperation(
            output=OutputProtocol(
                status="success",
                content="Successfully applied patch."
            ),
            files=files
        )
