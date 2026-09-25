from typing import override
import json

from openai import OpenAI
from openai.types.shared_params import Reasoning
from openai.types.responses import Response
from openai.types.responses import FunctionToolParam

from .base import BaseLLM

from ..tools.schema import ToolSchema
from ..tools.context import ToolOutput, ToolCall
from ..models.schema import TokenUsage, ModelData, ReasoningLevel

class OpenAILLM(BaseLLM[OpenAI]):
    def __init__(
            self,
            instructions: str,
            model_data: ModelData,
            reasoning: ReasoningLevel | None,
            max_iters: int
    ):
        super().__init__(
            instructions=instructions,
            model_data=model_data,
            reasoning=reasoning,
            max_iters=max_iters,
            client=OpenAI()
        )

    @override
    def tool_output_contract(
            self, results: list[tuple[ToolCall, ToolOutput]]
    ) -> list[dict]:
        return [
            {
                "type": "function_call_output",
                "call_id": call.id,
                "output": json.dumps(
                    output.to_context(),
                    ensure_ascii=False
                ),
            }
            for call, output in results
        ]

    @override
    def generate(
            self,
            input_: str | list[tuple[ToolCall, ToolOutput]],
            tools: list[ToolSchema],
            prev_id: str | None = None
            ) -> Response:
        kwargs = {}

        if self.reasoning is not None:
            kwargs["reasoning"] = Reasoning(
                effort=self.reasoning
            )

        if prev_id is not None:
            kwargs["previous_response_id"] = prev_id

        input_ = (
            input_
            if isinstance(input_, str)
            else self.tool_output_contract(input_)
        )

        response = self.client.responses.create(
            model=self.model_data.id,
            instructions=self.instructions,
            input=input_,
            tools=self.tool_schema_contract(
                tools=tools
            ),
            **kwargs
        )

        return response

    @override
    def usage(self, response: Response) -> TokenUsage:
        usage = response.usage

        return TokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.output_tokens_details.reasoning_tokens,
            total_tokens=usage.total_tokens,
            cached_input_tokens=usage.input_tokens_details.cached_tokens,
            cache_write_tokens=getattr(usage.input_tokens_details, "cache_write_tokens", None)
        )

    @override
    def output_text(self, response: Response) -> str:
        return response.output_text

    @override
    def tool_call_contract(self, response: Response) -> list[ToolCall]:
        return [
            ToolCall(
                name=item.name,
                args=json.loads(
                    item.arguments
                ),
                id=item.call_id
            )
            for item in response.output
            if item.type == "function_call"
        ]

    @override
    def tool_schema_contract(self, tools: list[ToolSchema]) -> list[FunctionToolParam]:
        return [
            {
                "type": "function",
                "name": tool_data.name,
                "description": tool_data.description,
                "parameters": {
                    "type": "object",
                    "properties": tool_data.parameters.properties,
                    "required": tool_data.parameters.required,
                    "additionalProperties": tool_data.parameters.additional_properties
                },
                "strict": tool_data.strict,
            }
            for tool_data in tools
        ]

    @override
    def response_id(self, response: Response) -> str:
        return response.id
