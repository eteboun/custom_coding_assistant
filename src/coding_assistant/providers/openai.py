from pathlib import Path
from typing import override
import json

from openai import OpenAI
from openai.types.shared_params import Reasoning
from openai.types.responses import Response
from openai.types.responses import FunctionToolParam

from .base import BaseLLM
from .schemas import TokenUsage
from ..config import Config
from ..tools.content import ToolCall, ToolOutput

class OpenAILLM(BaseLLM[OpenAI]):
    def __init__(
            self,
            instructions: str,
            repo_path: Path,
            config: Config
    ):
        super().__init__(
            instructions=instructions,
            repo_path=repo_path,
            config=config,
            provider="openai",
            client=OpenAI()
        )

    @override
    def generate(
            self,
            inputs: str | list[ToolOutput],
            instructions: str
    ) -> Response:
        kwargs = {}

        if self.reasoning is not None:
            kwargs["reasoning"] = Reasoning(
                effort=self.reasoning
            )

        if self._last_response is not None:
            kwargs["previous_response_id"] = self._last_response.id

        inputs = (
            inputs
            if isinstance(inputs, str)
            else [
                    self.tool_output_contract(output)
                    for output in inputs
                ]
        )

        response = self.client.responses.create(
            model=self.model_data.id,
            instructions=instructions,
            input=inputs,
            tools=self.tool_contract(),
            **kwargs
        )

        self._last_response = response
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
            cache_write_tokens=usage.input_tokens_details.cache_write_tokens
        )

    @override
    def output_text(self, response: Response) -> str:
        return response.output_text

    @override
    def tool_call_contract(self, response: Response) -> list[ToolCall]:
        return [
            ToolCall(
                call_id=item.call_id,
                name=item.name,
                args=json.loads(
                    item.arguments
                ),
            )
            for item in response.output
            if item.type == "function_call"
        ]

    @override
    def tool_output_contract(self, tool_output: ToolOutput) -> dict[str, str]:
        return {
            "type": "function_call_output",
            "call_id": tool_output.call_id,
            "output": json.dumps(
                tool_output.output.serialize()
            ),
        }

    @override
    def tool_contract(self) -> list[FunctionToolParam]:
        return [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": tool.parameters.properties,
                    "required": tool.parameters.required,
                    "additionalProperties": tool.parameters.additional_properties
                },
                "strict": tool.strict,
            }
            for tool in self.tools.datas
        ]
