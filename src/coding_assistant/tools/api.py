from dataclasses import dataclass
from pathlib import Path
from typing import Self
from logging import getLogger

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .content import Tools
from .context import ToolCall, ToolOutput, ToolUsageError
from .schema import ToolSchema

logger = getLogger(__name__)

from collections.abc import Callable

ApprovalHandler = Callable[[str], bool]

@dataclass
class ToolsAPIResponse:
    output: ToolOutput


class ToolsAPI:
    def __init__(
            self,
            repo_path: Path,
            blocked_files: list[Path],
            blocked_dirs: list[Path]
    ) -> None:

        self._tools = Tools(
            repo_path=repo_path,
            blocked_files=blocked_files,
            blocked_dirs=blocked_dirs
        )
        self._validators = {
            name: Draft202012Validator({
                "type": schema.parameters.type,
                "properties": schema.parameters.properties,
                "required": schema.parameters.required,
                "additionalProperties": schema.parameters.additional_properties,
            })
            for name, schema in self._tools.data_mapping.items()
        }

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

    @staticmethod
    def _denied_response(reason: str) -> ToolsAPIResponse:
        return ToolsAPIResponse(
            output=ToolOutput(
                status="denied",
                message=reason,
            ),
        )

    def schemas(self) -> list[ToolSchema]:
        return list(
            self._tools.data_mapping.values()
        )

    def execute_call(
            self,
            call: ToolCall,
            approval_handler: ApprovalHandler | None = None,
    ) -> ToolsAPIResponse:
        try:
            if call.name not in self._tools.function_mapping:
                raise ToolUsageError(f"Tool {call.name} not found")

            tool = self._tools.function_mapping[call.name]
            tool_data = self._tools.data_mapping[call.name]

            validation_args = dict(call.args)
            if call.mutation_summary is not None:
                validation_args["change_summary"] = call.mutation_summary

            try:
                self._validators[call.name].validate(validation_args)

            except ValidationError as error:
                location = ".".join(
                    str(part) for part in error.absolute_path
                )

                message = error.message
                if location:
                    message = f"{location}: {message}"

                raise ToolUsageError(
                    f"Invalid arguments for tool '{call.name}': {message}"
                ) from error

            if (
                    tool_data.metadata.mutative
                    and not call.mutation_summary.strip()
            ):
                raise ToolUsageError(
                    f"Tool {call.name} requires a nonempty mutation summary"
                )

            approval = tool_data.metadata.approval
            if approval is not None:
                message = approval.template.format(**call.args)

                if approval_handler is None:
                    raise RuntimeError(
                        f"Approval handler required for tool '{call.name}'"
                    )

                if not approval_handler(message):
                    return self._denied_response(
                        reason="the user denied approval"
                    )

            output = tool(**call.args)

        except ToolUsageError as error:
            return ToolsAPIResponse(
                output=ToolOutput(
                    status="error",
                    message=str(error),
                ),
            )

        return ToolsAPIResponse(
            output=output,
        )
