import shutil
import subprocess
import tempfile
import uuid
import hashlib
import os
from logging import getLogger
from pathlib import Path

from ..mutation import Mutation, Operation
from .results import OperationResult
from .errors import BackendDeveloperError, BackendUsageError
from .path_policy import is_blocked_path, normalize_blocked_paths

logger = getLogger(__name__)


class Sandbox:
    def __init__(
        self,
        repo_path: Path,
        *,
        blocked_files: list[Path] | None = None,
        blocked_dirs: list[Path] | None = None,
        image: str = "python:3.13-slim",
        memory: str = "512m",
        cpus: float = 1.0,
        pids_limit: int = 64,
        timeout: float = 30.0,
    ) -> None:
        self.repo_path = repo_path.resolve()

        self.blocked_files = normalize_blocked_paths(blocked_files or [])
        self.blocked_dirs = normalize_blocked_paths(blocked_dirs or [])

        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.timeout = timeout

        self.container_name = f"coding-agent-{uuid.uuid4().hex[:12]}"
        self._started = False
        self._mask_root: Path | None = None

    def _blocked_paths(self) -> list[tuple[Path, bool]]:
        blocked: list[tuple[Path, bool]] = []

        for relative in sorted(self.blocked_files | self.blocked_dirs):
            if any(parent in self.blocked_dirs for parent in relative.parents):
                continue

            path = self.repo_path / relative
            if path.is_dir():
                blocked.append((relative, True))
            elif path.exists() or path.is_symlink():
                blocked.append((relative, False))

        return sorted(blocked, key=lambda entry: entry[0].as_posix())

    def _mask_mount_args(self) -> list[str]:
        blocked = self._blocked_paths()
        if not blocked:
            return []

        self._mask_root = Path(tempfile.mkdtemp(prefix="coding-agent-mask-"))
        empty_file = self._mask_root / "empty-file"
        empty_directory = self._mask_root / "empty-directory"
        empty_file.touch()
        empty_directory.mkdir()

        args: list[str] = []
        for relative, is_directory in blocked:
            source = empty_directory if is_directory else empty_file
            target = f"/workspace/{relative.as_posix()}"
            args.extend([
                "--mount",
                f"type=bind,source={source},target={target},readonly",
            ])

        return args

    def _cleanup_mask_sources(self) -> None:
        if self._mask_root is None:
            return

        shutil.rmtree(self._mask_root)
        self._mask_root = None

    def start(self) -> None:
        if self._started:
            return

        try:
            mask_mount_args = self._mask_mount_args()
            result = subprocess.run(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--name",
                    self.container_name,
                    "--network",
                    "none",
                    "--memory",
                    self.memory,
                    "--cpus",
                    str(self.cpus),
                    "--pids-limit",
                    str(self.pids_limit),
                    "--mount",
                    f"type=bind,source={self.repo_path},target=/workspace",
                    *mask_mount_args,
                    "--workdir",
                    "/workspace",
                    self.image,
                    "sleep",
                    "infinity",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8", errors="replace", timeout=30,
            )

            if result.returncode != 0:
                raise BackendDeveloperError(
                    f"Failed to start sandbox: {result.stderr.strip()}"
                )

            self._started = True

        except Exception:
            try:
                self._remove_container()
            except Exception:
                logger.exception(
                    "Failed to remove sandbox container after start failure."
                )

            try:
                self._cleanup_mask_sources()
            except Exception:
                logger.exception(
                    "Failed to remove sandbox mask sources after start failure."
                )

            raise

    def stop(self) -> None:
        if not self._started:
            return

        self._remove_container()
        self._started = False
        self._cleanup_mask_sources()

    def _remove_container(self) -> None:
        result = subprocess.run(
            [
                "docker",
                "rm",
                "-f",
                self.container_name,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8", errors="replace", timeout=30,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()

            if "No such container" in stderr:
                return

            raise BackendDeveloperError(
                f"Failed to remove sandbox: {stderr}"
            )

    def _repo_snapshot(self) -> dict[str, tuple[str, str]]:
        snapshot: dict[str, tuple[str, str]] = {}

        def walk(directory: Path) -> None:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    relative = path.relative_to(self.repo_path)
                    if is_blocked_path(relative, self.blocked_files, self.blocked_dirs):
                        continue

                    key = relative.as_posix()
                    if entry.is_symlink():
                        snapshot[key] = ("symlink", os.readlink(entry.path))
                    elif entry.is_dir(follow_symlinks=False):
                        snapshot[key] = ("directory", "")
                        walk(path)
                    elif entry.is_file(follow_symlinks=False):
                        digest = hashlib.sha256()
                        with open(entry.path, "rb") as file:
                            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                                digest.update(chunk)
                        snapshot[key] = ("file", digest.hexdigest())

        walk(self.repo_path)
        return snapshot

    @staticmethod
    def _snapshot_mutations(
        before: dict[str, tuple[str, str]],
        after: dict[str, tuple[str, str]],
    ) -> tuple[Mutation, ...]:
        mutations = []
        for path in sorted(before.keys() | after.keys()):
            if path not in before:
                operation = Operation.ADD
            elif path not in after:
                operation = Operation.DELETE
            elif before[path] != after[path]:
                operation = Operation.UPDATE
            else:
                continue
            mutations.append(
                Mutation(path=path, type=operation)
            )
        return tuple(mutations)

    def run_command(self, command: str) -> OperationResult:
        if not self._started:
            raise BackendDeveloperError("Sandbox is not running.")

        before = self._repo_snapshot()
        try:
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    self.container_name,
                    "sh",
                    "-lc",
                    command,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8", errors="replace",
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            # Killing the docker CLI does not kill the command inside the container.
            # Replace the container before allowing further agent work so a timed-out
            # process cannot keep modifying the repository in the background.
            self.stop()
            self.start()
            raise BackendUsageError(
                f"Command timed out after {self.timeout} seconds.",
            ) from exc

        mutations = self._snapshot_mutations(before, self._repo_snapshot())
        return OperationResult(
            content={
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            },
            files=tuple(mutation.path for mutation in mutations),
            mutations=mutations,
        )
