import subprocess
import json
from pathlib import Path
from typing import ClassVar

from .apply_patch import _parse_patch, _apply_update, _parse_added_file
from .context import ToolOutput, Mutation, Operation, ToolUsageError, LearningMetadata
from ..utils import OutputProtocol, ToolEnvironmentError

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
                "Access outside the repository is denied",
                learning=LearningMetadata(
                    persistent=True,
                    key="workspace.outside_repository"
                )
            )

        relative = full_path.relative_to(self.repo_path)

        if full_path.name in self.blocked_files:
            raise ToolUsageError(
                f"{relative.as_posix()} is not accessible"
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

    def search_files(
            self,
            pattern: str | None = None,
            max_results: int = 100
    ) -> ToolOutput:
        if max_results < 1:
            raise ToolUsageError(
                "max_results must be at least 1.",
                learning=LearningMetadata(
                    persistent=True,
                    key="search_files.max_results_below_minimum",
                ),
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

        return ToolOutput(
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
    ) -> ToolOutput:

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

            return ToolOutput(
                output=OutputProtocol(
                    status="success",
                    content="\n".join(findings)
                ),
                files=tuple(sorted(files))
            )

        if result.returncode == 1:
            return ToolOutput(
                output=OutputProtocol(
                    status="success",
                    content="No match found"
                )
            )

        raise ToolEnvironmentError(
            f"ripgrep failed: {result.stderr.strip()}"
        )

    def repo_tree(self) -> ToolOutput:
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

        return ToolOutput(
            output=OutputProtocol(
                status="success",
                content="\n".join(lines),
            ),
            files=tuple(files)
        )

    def list_directory(self, path: str) -> ToolOutput:
        resolved_dir = self._resolve_dir(path=path)

        entries = sorted(
            e.name
            for e in resolved_dir.content.iterdir()
            if self._is_allowed_path(e)
        )

        return ToolOutput(
            output=OutputProtocol(
                status="success",
                content=entries
            ),
            files=tuple(entries)
        )

    def delete_dir(self, path: str) -> ToolOutput:
        resolved_dir = self._resolve_dir(path=path)
        full_path = resolved_dir.content

        relative_path = full_path.relative_to(
            self.repo_path
        ).as_posix()

        try:
            full_path.rmdir()
        except OSError as e:
            raise ToolUsageError(str(e)) from e

        return ToolOutput(
            output=OutputProtocol(
                status="success",
                content=relative_path
            ),
            files=(relative_path,),
            mutations=(
                Mutation(
                    path=relative_path,
                    type=Operation.DELETE
                ),
            )
        )

    def read_file(
        self,
        path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> ToolOutput:
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

        return ToolOutput(
            output=OutputProtocol(
                status="success",
                content="".join(numbered_lines)
            ),
            files=(relative,)
        )

    def apply_patch(
            self,
            patch: str,
    ) -> ToolOutput:
        patch = patch.replace("\r\n", "\n").replace("\r", "\n")

        file_patches = _parse_patch(patch)

        pending_writes: dict[Path, str] = {}
        pending_deletes: set[Path] = set()

        for file_patch in file_patches:
            if file_patch.operation == "update":
                resolved = self._resolve_file(file_patch.path)
                full_path = resolved.content

                with open(full_path, "r", encoding="utf-8", newline="") as f:
                    initial_content = f.read()

                try:
                    new_content = _apply_update(
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
                    new_content = _parse_added_file(
                        file_patch.lines
                    )
                except ValueError as e:
                    raise ToolUsageError(
                        f"{file_patch.path}: {e}"
                    ) from e

                pending_writes[full_path] = new_content

        if pending_deletes & pending_writes.keys():
            raise ToolUsageError(
                "A file cannot be both written and deleted.",
                learning=LearningMetadata(
                    persistent=True,
                    key="apply_patch.conflicting_file_operations"
                )
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

        files = tuple(sorted(
            {
                Path(patch.path).as_posix()
                for patch in file_patches
            }
        ))

        mutations = tuple(
            Mutation(
                path=patch.path,
                type=patch.operation
            ) for patch in file_patches
        )

        return ToolOutput(
            output=OutputProtocol(
                status="success",
                content="Successfully applied patch."
            ),
            files=files,
            mutations=mutations
        )
