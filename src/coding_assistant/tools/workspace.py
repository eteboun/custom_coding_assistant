import subprocess
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import ClassVar

from .apply_patch import _parse_patch, _apply_update, _parse_added_file
from .context import ToolOutput, Mutation, Operation, ToolUsageError, LearningMetadata
from .path_policy import is_blocked_path, normalize_blocked_paths
from ..utils import ToolEnvironmentError


class PatchRollbackError(Exception):
    pass

class Workspace:

    REPO_TREE_MAX_DEPTH: ClassVar[int] = 4

    def __init__(self,
                 repo_path: Path,
                 blocked_files: list[Path],
                 blocked_dirs: list[Path]
                 ) -> None:

        self.repo_path = repo_path.resolve()
        self.blocked_files = normalize_blocked_paths(blocked_files)
        self.blocked_dirs = normalize_blocked_paths(blocked_dirs)

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
            message = result.stderr.strip()

            if "regex parse error" in message:
                raise ToolUsageError(
                    "When using regex search, provide a valid ripgrep regular expression.",
                    learning=LearningMetadata(
                        persistent=True,
                        key="ripgrep.invalid_regex"
                    )
                )

            raise ToolEnvironmentError(
                f"ripgrep failed: {message}"
            )

        return result

    def _resolve_path(
            self,
            path: str,
    ) -> Path:
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
        lexical_path = Path(os.path.abspath(self.repo_path / path))
        try:
            lexical_relative = lexical_path.relative_to(self.repo_path)
        except ValueError as error:
            raise ToolUsageError(
                "Access outside the repository is denied"
            ) from error

        if any(
            is_blocked_path(candidate, self.blocked_files, self.blocked_dirs)
            for candidate in (relative, lexical_relative)
        ):
            raise ToolUsageError(
                "Path is not accessible"
            )

        return full_path

    def _resolve_dir(
            self,
            path: str
    ) -> Path:

        resolved_path = self._resolve_path(
            path=path
        )

        if not resolved_path.exists():
            raise ToolUsageError(
                f"Directory {path} does not exist"
            )

        if not resolved_path.is_dir():
            raise ToolUsageError(
                f"{path} is not a directory"
            )

        return resolved_path

    def _resolve_file(
            self,
            path: str
    ) -> Path:
        resolved_path = self._resolve_path(
            path=path
        )

        if not resolved_path.exists():
            raise ToolUsageError(
                f"File {path} does not exist"
            )

        if not resolved_path.is_file():
            raise ToolUsageError(
                f"{path} is not a file"
            )

        return resolved_path

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

        for directory in sorted(self.blocked_dirs):
            cmd += ["-g", f"!/{directory.as_posix()}/**"]

        for file in sorted(self.blocked_files):
            cmd += ["-g", f"!/{file.as_posix()}"]

        result = self._run_ripgrep(
            cmd=cmd,
            cwd=self.repo_path
        )

        files: set[str] = set()

        for raw_path in result.stdout.splitlines():
            try:
                full_path = self._resolve_path(raw_path)
            except ToolUsageError:
                continue

            relative = full_path.relative_to(self.repo_path).as_posix()
            files.add(relative)

            if len(files) >= max_results:
                break

        sorted_files = sorted(files)

        return ToolOutput(
            status="success",
            content=sorted_files,
            files=tuple(sorted_files)
        )

    def search_text(
            self,
            text: str,
            regex: bool = False,
            context_lines: int = 2,
            max_output_lines: int = 100
    ) -> ToolOutput:

        if context_lines < 0:
            raise ToolUsageError(
                "context_lines must be >= 0.",
            )

        if max_output_lines < 1:
            raise ToolUsageError(
                "max_output_lines must be >= 1.",
            )

        cmd = [
            "rg",
            "--json",
            "-C",
            str(context_lines)
        ]

        if not regex:
            cmd.append("--fixed-strings")

        for file in sorted(self.blocked_files):
            cmd.extend(["-g", f"!/{file.as_posix()}"])

        for directory in sorted(self.blocked_dirs):
            cmd.extend(["-g", f"!/{directory.as_posix()}/**"])

        cmd.extend([
            "--",
            text,
            self.repo_path.as_posix()
        ])

        result = self._run_ripgrep(
            cmd=cmd,
            cwd=self.repo_path,
        )

        if result.returncode == 0:
            files: set[str] = set()
            findings: list[str] = []

            lines = 0
            full_paths: dict[str, Path] = {}
            for line in result.stdout.splitlines():
                event = json.loads(line)

                if event["type"] not in ("match", "context"):
                    continue

                path = event["data"]["path"]["text"]
                line_number = event["data"]["line_number"]
                line_text = event["data"]["lines"]["text"].rstrip("\n")

                try:
                    full_path = full_paths.get(path)
                    if full_path is None:
                        full_path = self._resolve_file(path=path)

                        full_paths[path] = full_path

                except ToolUsageError:
                    continue

                relative = full_path.relative_to(
                    self.repo_path
                ).as_posix()

                files.add(relative)
                findings.append(
                    f"{relative}:{line_number}:{line_text}"
                )

                lines += 1
                if lines >= max_output_lines:
                    break

            sorted_files = sorted(files)

            return ToolOutput(
                status="success",
                content="\n".join(findings),
                files=tuple(sorted_files)
            )

        if result.returncode == 1:
            return ToolOutput(
                status="success",
                content="No match found"
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
                try:
                    full_path = self._resolve_path(
                        path=entry.as_posix()
                    )

                except ToolUsageError:
                    continue

                relative = full_path.relative_to(
                    self.repo_path
                ).as_posix()

                files.append(relative)

                indent = "    " * depth

                if entry.is_dir():
                    lines.append(f"{indent}{entry.name}/")
                    walk(entry, depth + 1)
                else:
                    lines.append(f"{indent}{entry.name}")

        walk(self.repo_path, 0)

        files.sort()

        return ToolOutput(
            status="success",
            content="\n".join(lines),
            files=tuple(files)
        )

    def list_directory(self, path: str) -> ToolOutput:
        full_dir_path = self._resolve_dir(path=path)

        entries: list[str] = []
        for path in full_dir_path.iterdir():
            try:
                full_path = self._resolve_path(
                    path=path.as_posix()
                )
            except ToolUsageError:
                continue

            relative = full_path.relative_to(
                self.repo_path
            ).as_posix()

            entries.append(relative)

        entries.sort()

        return ToolOutput(
            status="success",
            content=entries,
            files=tuple(entries)
        )

    def delete_directory(self, path: str) -> ToolOutput:
        full_path = self._resolve_dir(path=path)

        try:
            full_path.rmdir()
        except OSError as e:
            raise ToolUsageError(str(e)) from e

        relative = full_path.relative_to(
            self.repo_path
        ).as_posix()

        return ToolOutput(
            status="success",
            content=relative,
            files=(relative,),
            mutations=(
                Mutation(
                    path=relative,
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
        if start_line is not None and start_line < 1:
            raise ToolUsageError(
                "start_line must be positive when provided."
            )

        if end_line is not None and end_line < 1:
            raise ToolUsageError(
                "end_line must be positive when provided."
            )

        full_path = self._resolve_file(path=path)

        relative = full_path.relative_to(
            self.repo_path
        ).as_posix()

        with open(full_path, encoding="utf-8") as f:
            lines = f.readlines()

        file_length = len(lines)
        if file_length == 0:
            raise ToolUsageError(f"File {relative} is empty.")

        start = start_line if start_line is not None else 1
        end = end_line if end_line is not None else file_length

        if start > file_length:
            raise ToolUsageError(
                f"start_line {start} exceeds file length {file_length}."
            )

        if end < start:
            raise ToolUsageError(
                "end_line must be greater than or equal to start_line."
            )

        end = min(end, file_length)

        numbered_line_group = zip(
            range(start, end + 1),
            lines[start - 1:end]
        )

        numbered_lines = []
        for num, line in numbered_line_group:
            numbered_lines.append(
                f"{num} | {line}"
            )

        return ToolOutput(
            status="success",
            content="".join(numbered_lines),
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
        original_paths: set[Path] = set()
        canonical_paths: dict[str, str] = {}
        resolved_targets: dict[str, str] = {}

        for file_patch in file_patches:
            if file_patch.operation == "update":
                full_path = self._resolve_file(file_patch.path)

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
                original_paths.add(full_path)

            elif file_patch.operation == "delete":
                full_path = self._resolve_file(file_patch.path)

                if file_patch.lines:
                    raise ToolUsageError(
                        f"{file_patch.path}: Delete File "
                        "must not contain patch content."
                    )

                pending_deletes.add(full_path)
                original_paths.add(full_path)

            elif file_patch.operation == "add":
                full_path = self._resolve_path(file_patch.path)

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

            canonical_key = os.path.normcase(os.fspath(full_path))
            previous = resolved_targets.get(canonical_key)
            if previous is not None:
                raise ToolUsageError(
                    f"Patch paths {previous!r} and {file_patch.path!r} "
                    "resolve to the same file."
                )

            resolved_targets[canonical_key] = file_patch.path
            canonical_paths[file_patch.path] = full_path.relative_to(
                self.repo_path
            ).as_posix()

        if pending_deletes & pending_writes.keys():
            raise ToolUsageError(
                "A file cannot be both written and deleted.",
                learning=LearningMetadata(
                    persistent=True,
                    key="apply_patch.conflicting_file_operations"
                )
            )

        staged_writes: dict[Path, Path] = {}
        created_directories: list[Path] = []

        try:
            for path, content in pending_writes.items():
                missing_directories: list[Path] = []
                parent = path.parent

                while not parent.exists():
                    missing_directories.append(parent)
                    parent = parent.parent

                for directory in reversed(missing_directories):
                    directory.mkdir()
                    created_directories.append(directory)

                staged_path = path.with_name(
                    f".{path.name}.coding-agent-stage-{uuid.uuid4().hex}"
                )
                descriptor = os.open(
                    staged_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o666,
                )

                try:
                    with os.fdopen(
                            descriptor,
                            "w",
                            encoding="utf-8",
                            newline="",
                    ) as file:
                        file.write(content)
                        file.flush()
                        os.fsync(file.fileno())
                except Exception:
                    staged_path.unlink(missing_ok=True)
                    raise

                staged_writes[path] = staged_path

                if path in original_paths:
                    shutil.copystat(path, staged_path)

        except Exception:
            for staged_path in staged_writes.values():
                staged_path.unlink(missing_ok=True)

            for directory in reversed(created_directories):
                try:
                    directory.rmdir()
                except OSError:
                    pass

            raise

        backups = {
            path: path.with_name(
                f".{path.name}.coding-agent-backup-{uuid.uuid4().hex}"
            )
            for path in original_paths
        }
        moved_backups: list[tuple[Path, Path]] = []
        installed_paths: list[Path] = []

        try:
            for path in sorted(original_paths):
                backup = backups[path]
                os.replace(path, backup)
                moved_backups.append((path, backup))

            for path, staged_path in staged_writes.items():
                os.replace(staged_path, path)
                installed_paths.append(path)

        except Exception as commit_error:
            rollback_errors: list[tuple[Path, Exception]] = []

            for path in reversed(installed_paths):
                if path not in backups:
                    try:
                        path.unlink(missing_ok=True)
                    except Exception as error:
                        rollback_errors.append((path, error))

            for path, backup in reversed(moved_backups):
                try:
                    os.replace(backup, path)
                except Exception as error:
                    rollback_errors.append((path, error))

            for staged_path in staged_writes.values():
                try:
                    staged_path.unlink(missing_ok=True)
                except Exception as error:
                    rollback_errors.append((staged_path, error))

            for directory in reversed(created_directories):
                try:
                    directory.rmdir()
                except OSError as error:
                    if directory.exists():
                        rollback_errors.append((directory, error))

            if rollback_errors:
                paths = ", ".join(
                    sorted({path.as_posix() for path, _ in rollback_errors})
                )
                raise PatchRollbackError(
                    "Patch application failed and rollback was incomplete. "
                    f"The following paths may be inconsistent: {paths}"
                ) from commit_error

            raise

        cleanup_warnings: list[str] = []
        for _, backup in moved_backups:
            try:
                backup.unlink()
            except OSError:
                cleanup_warnings.append(backup.as_posix())

        files = tuple(sorted(
            {
                canonical_paths[patch.path]
                for patch in file_patches
            }
        ))

        mutations = tuple(
            Mutation(
                path=canonical_paths[patch.path],
                type=patch.operation
            ) for patch in file_patches
        )

        message = "Successfully applied patch."
        if cleanup_warnings:
            message += (
                " Original-file backups could not be removed: "
                + ", ".join(cleanup_warnings)
            )

        return ToolOutput(
            status="success",
            content=message,
            files=files,
            mutations=mutations
        )
