from dataclasses import dataclass
from pathlib import Path

from .content import Tools
from .context import (ToolCall, ToolOutput, ToolUsageError,
                      UpdateScope, Operation, Invalidation)

from ..utils import OutputProtocol

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

        self.tools = Tools(
            repo_path=config.repo_path,
            blocked_files=config.blocked_files,
            blocked_dirs=config.blocked_dirs
        )

    def execute_call(self, call: ToolCall) -> ToolsAPIResponse:
        try:
            if call.name not in self.tools.function_mapping:
                raise ToolUsageError(
                    f"Tool {call.name} not found"
                )

            tool = self.tools.function_mapping[call.name]
            tool_data = self.tools.data_mapping[call.name]

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
            update_scope=tool_data.update_scope
        )

