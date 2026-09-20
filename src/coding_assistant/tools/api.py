from dataclasses import dataclass
from pathlib import Path
from typing import Self
from logging import getLogger

from .content import Tools
from .context import (ToolCall, ToolOutput, ToolUsageError,
                      UpdateScope, Operation, Invalidation)
from .schema import ToolSchema

from ..utils import OutputProtocol

logger = getLogger(__name__)

@dataclass
class ToolsAPIConfig:
    repo_path: Path
    blocked_files: list[str]
    blocked_dirs: list[str]

@dataclass
class ToolsAPIResponse:
    output: ToolOutput
    update_when: dict[Operation, Invalidation]
    update_scope: UpdateScope | None

    def is_fail(self) -> bool:
        return self.output.is_fail()

class ToolsAPI:
    def __init__(self, config: ToolsAPIConfig) -> None:
        self.config = config
        self.repo_path = config.repo_path

        self._tools = Tools(
            repo_path=config.repo_path,
            blocked_files=config.blocked_files,
            blocked_dirs=config.blocked_dirs
        )

    def __enter__(self) -> Self:
        self._tools.sandbox.start()
        return self

    def __exit__(
            self,
            exc_type,
            exc_value,
            traceback,
    ) -> bool:
        try:
            self._tools.sandbox.stop()
        except Exception:
            if exc_value is None:
                raise

            logger.exception(
                "Failed to stop sandbox during exception cleanup."
            )

        return False

    def approval_message(
            self,
            call: ToolCall,
    ) -> str | None:
        tool = self._tools.data_mapping.get(call.name)

        if tool is None or tool.metadata.approval is None:
            return None

        return tool.metadata.approval.message_template.format(
            **call.args
        )

    @staticmethod
    def denied_response(call: ToolCall) -> ToolsAPIResponse:
        return ToolsAPIResponse(
            output=ToolOutput(
                output=OutputProtocol(
                    status="error",
                    message=(
                        f"Tool '{call.name}' was not executed "
                        "because the user denied approval."
                    ),
                )
            ),
            update_when={},
            update_scope=None
        )

    def schemas(self) -> list[ToolSchema]:
        return self._tools.data_mapping.values()

    def execute_call(self, call: ToolCall) -> ToolsAPIResponse:
        try:
            if call.name not in self._tools.function_mapping:
                raise ToolUsageError(
                    f"Tool {call.name} not found"
                )

            tool = self._tools.function_mapping[call.name]
            tool_data = self._tools.data_mapping[call.name]

            if (
                    tool_data.metadata.mutative
                    and (
                        call.mutation_summary is None
                        or not call.mutation_summary.strip()
                )
            ):
                raise ToolUsageError(
                    f"Tool {call.name} requires mutation summary"
                )

            output = tool(**call.args)

        except ToolUsageError as e:
            output = ToolOutput(
                output=OutputProtocol(
                    status="error",
                    message=str(e)
                ),
                learning_metadata=e.learning
            )
            return ToolsAPIResponse(
                output=output,
                update_when={},
                update_scope=None
            )

        return ToolsAPIResponse(
            output=output,
            update_when=tool_data.metadata.update_when,
            update_scope=tool_data.metadata.update_scope
        )
