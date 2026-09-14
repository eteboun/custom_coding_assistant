import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ..utils import OutputProtocol

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
    ) -> OutputProtocol:
        full_path = (self.repo_path / path).resolve()

        if not full_path.is_relative_to(self.repo_path):
            return OutputProtocol(
                status="error",
                message= "Access outside the repository is denied"
            )

        if full_path.name in self.blocked_files:
            return OutputProtocol(
                status="error",
                message="Path is not accessible"
            )

        relative_parts = full_path.relative_to(self.repo_path).parts

        if any(part in self.blocked_dirs for part in relative_parts):
            return OutputProtocol(
                status="error",
                message="Path is not accessible"
            )

        return OutputProtocol(
            status="success",
            content=full_path
        )

    def resolve_dir(
            self,
            path: str
    ) -> OutputProtocol:

        resolved_path = self.resolve_path(
            path=path
        )

        if resolved_path.is_fail():
            return resolved_path

        full_path = resolved_path.content

        if not full_path.exists():
            return OutputProtocol(
                status="error",
                message=f"Directory {path} does not exist",
            )

        if not full_path.is_dir():
            return OutputProtocol(
                status="error",
                message=f"{path} is not a directory"
            )

        return OutputProtocol(
            status="success",
            content=full_path,
        )

    def resolve_file(
            self,
            path: str
    ) -> OutputProtocol:
        resolved_path = self.resolve_path(
            path=path
        )

        if resolved_path.is_fail():
            return resolved_path

        full_path = resolved_path.content

        if not full_path.exists():
            return OutputProtocol(
                status="error",
                message=f"File {path} does not exist",
            )

        if not full_path.is_file():
            return OutputProtocol(
                status="error",
                message=f"{path} is not a file",
            )

        return OutputProtocol(
            status="success",
            content=full_path,
        )

    def search_files(
            self,
            pattern: str | None = None,
            max_results: int = 100,
    ) -> OutputProtocol:
        if max_results < 1:
            return OutputProtocol(
                status="error",
                message="max_results must be at least 1.",
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

        result = subprocess.run(
            cmd,
            cwd=self.repo_path,
            capture_output=True,
            text=True,
        )

        if result.returncode not in (0, 1):
            return OutputProtocol(
                status="error",
                message=result.stderr.strip(),
            )

        files = []

        for path in result.stdout.splitlines():
            if not self.is_allowed_path(path=Path(path)):
                continue

            files.append(path)

            if len(files) >= max_results:
                break

        return OutputProtocol(
            status="success",
            content=files,
        )

    def search_text(self,
                    text: str,
                    context_lines: int = 2,
                    max_output_lines: int = 100
                    ) -> OutputProtocol:
        try:
            command = [
                "rg",
                "-n",
                "-C",
                str(context_lines),
                text,
                self.repo_path.as_posix(),
            ]

            for file in self.blocked_files:
                command.extend(["-g", f"!{file}"])

            for directory in self.blocked_dirs:
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

    def is_allowed_file(
            self,
            path: Path
    ) -> bool:
        resolved_file = self.resolve_file(
            path=path.as_posix()
        )

        return not resolved_file.is_fail()

    def is_allowed_dir(
            self,
            path: Path
    ) -> bool:
        resolved_dir = self.resolve_dir(
            path=path.as_posix()
        )

        return not resolved_dir.is_fail()

    def is_allowed_path(
            self,
            path: Path
    ) -> bool:
        resolved_path = self.resolve_path(
            path=path.as_posix()
        )

        return not resolved_path.is_fail()

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
