from pathlib import Path
from typing import override
from pydantic import BaseModel
import json

from openai import OpenAI
from openai.types.shared_params import Reasoning
from openai.types.responses import Response, ParsedResponse
from openai.types.responses import FunctionToolParam

from .base import BaseLLM
from ..ai.schemas import TokenUsage
from ..ai.config import Config
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

    def _generate(
            self,
            inputs,
            instructions: str,
            prev_id: str | None = None
    ) -> Response:
        kwargs = {}

        if self.config.reasoning is not None:
            kwargs["reasoning"] = Reasoning(
                effort=self.config.reasoning
            )

        if prev_id is not None:
            kwargs["previous_response_id"] = prev_id

        return self.client.responses.create(
            model=self.model_data.id,
            instructions=instructions,
            input=inputs,
            tools=self.tool_contract(),
            **kwargs
        )

    def _parse[T: BaseModel](
            self,
            inputs,
            response_format: type[T],
            instructions: str
    ) -> ParsedResponse:
        return self.client.responses.parse(
            model=self.model_data.id,
            instructions=instructions,
            input=inputs,
            text_format=response_format
        )

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
                "parameters": tool.parameters.serialize(),
                "strict": tool.strict,
            }
            for tool in self.tools.datas
        ]

    @override
    def initial_call(self, query: str, instructions: str) -> Response:
        return self._generate(
            inputs=query,
            instructions=instructions
        )

    @override
    def next_call(
            self,
            outputs: list[ToolOutput],
            response: Response,
            instructions: str
    ) -> Response:
        return self._generate(
            inputs=[
                self.tool_output_contract(output)
                for output in outputs
            ],
            prev_id=response.id,
            instructions=instructions
        )