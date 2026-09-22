import os
import shutil
import subprocess
import tempfile
import uuid
from logging import getLogger
from pathlib import Path

from .context import ToolOutput, ToolUsageError

logger = getLogger(__name__)

class SandboxError(Exception):
    pass

class Sandbox:
    def __init__(
        self,
        repo_path: Path,
        *,
        blocked_files: list[str] | None = None,
        blocked_dirs: list[str] | None = None,
        image: str = "python:3.13-slim",
        memory: str = "512m",
        cpus: float = 1.0,
        pids_limit: int = 64,
        timeout: float = 30.0,
    ) -> None:
        self.repo_path = repo_path.resolve()
        self.blocked_files = set(blocked_files or [])
        self.blocked_dirs = set(blocked_dirs or [])
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

        for root, directories, files in os.walk(
                self.repo_path,
                followlinks=False,
        ):
            root_path = Path(root)
            allowed_directories: list[str] = []

            for name in directories:
                path = root_path / name

                if name in self.blocked_dirs or name in self.blocked_files:
                    blocked.append((path.relative_to(self.repo_path), True))
                else:
                    allowed_directories.append(name)

            directories[:] = allowed_directories

            for name in files:
                if name in self.blocked_files or name in self.blocked_dirs:
                    path = root_path / name
                    blocked.append((path.relative_to(self.repo_path), False))

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
            )

            if result.returncode != 0:
                raise SandboxError(
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
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()

            if "No such container" in stderr:
                return

            raise SandboxError(
                f"Failed to remove sandbox: {stderr}"
            )

    def run_command(self, command: str) -> ToolOutput:
        if not self._started:
            raise SandboxError("Sandbox is not running.")

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
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ToolUsageError(
                f"Command timed out after {self.timeout} seconds."
            ) from exc

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        message = f"Exit code: {result.returncode}"

        if stdout:
            message += f"\nStdout:\n{stdout}"

        if stderr:
            message += f"\nStderr:\n{stderr}"

        return ToolOutput(
            status="success",
            content=message
        )
