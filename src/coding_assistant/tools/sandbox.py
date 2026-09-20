import subprocess
import uuid
from logging import getLogger
from pathlib import Path

from .context import ToolOutput, ToolUsageError
from ..utils import OutputProtocol

logger = getLogger(__name__)

class SandboxError(Exception):
    pass

class Sandbox:
    def __init__(
        self,
        repo_path: Path,
        *,
        image: str = "python:3.13-slim",
        memory: str = "512m",
        cpus: float = 1.0,
        pids_limit: int = 64,
        timeout: float = 30.0,
    ) -> None:
        self.repo_path = repo_path.resolve()
        self.image = image
        self.memory = memory
        self.cpus = cpus
        self.pids_limit = pids_limit
        self.timeout = timeout

        self.container_name = f"coding-agent-{uuid.uuid4().hex[:12]}"
        self._started = False

    def start(self) -> None:
        if self._started:
            return

        try:
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

            raise

    def stop(self) -> None:
        if not self._started:
            return

        self._remove_container()
        self._started = False

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
            output=OutputProtocol(
                status="success",
                content=message
            )
        )
