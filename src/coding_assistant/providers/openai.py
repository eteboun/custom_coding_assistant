from pathlib import Path
from typing import override
import json

from openai import OpenAI
from openai.types.shared_params import Reasoning
from openai.types.responses import Response
from openai.types.responses import FunctionToolParam

from .base import BaseLLM

from ..models.schema import TokenUsage
from ..config import Config
from ..tools.context import ToolCall

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
    def generate(self) -> Response:
        kwargs = {}

        if self.reasoning is not None:
            kwargs["reasoning"] = Reasoning(
                effort=self.reasoning
            )

        response = self.client.responses.create(
            model=self.model_data.id,
            instructions=self.instructions,
            input=self.memory.format_context(),
            tools=self.tool_contract(),
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
            cache_write_tokens=usage.input_tokens_details.cache_write_tokens
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
            )
            for item in response.output
            if item.type == "function_call"
        ]

    @override
    def tool_contract(self) -> list[FunctionToolParam]:
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
            for tool_data in self.tools.data_mapping.values()
        ]
