from .content import Tools
from .context import ToolCall, ToolOutput, ToolUsageError

from ..utils import OutputProtocol

class Executor:
    def __init__(self, tools: Tools) -> None:
        self.tools = tools

    def execute_call(self, call: ToolCall) -> ToolOutput:
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

            output = tool(self, **call.args)

        except ToolUsageError as e:
            output = ToolOutput(
                output=OutputProtocol(
                    status="error",
                    message=str(e)
                ),
                learning_metadata=e.learning
            )

        return output
