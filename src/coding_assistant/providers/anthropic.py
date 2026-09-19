from pathlib import Path
from typing import override

from anthropic import Anthropic
from anthropic.types import (ToolParam, MessageParam,
                             ThinkingConfigAdaptiveParam, OutputConfigParam,
                             Message)

from .base import BaseLLM

from ..models.schema import TokenUsage
from ..config import Config
from ..tools.context import ToolCall

class AnthropicLLM(BaseLLM[Anthropic]):
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
            provider="anthropic",
            client=Anthropic()
        )

    @override
    def generate(self) -> Message:
        kwargs = {}

        if self.reasoning is not None:
            kwargs["output_config"] = OutputConfigParam(
                effort=self.reasoning
            )

        messages: list[MessageParam] = [
                    {
                        "role": "user",
                        "content": self.memory.format_context()
                    }
                ]

        with self.client.messages.stream(
                model=self.model_data.id,
                max_tokens=self.model_data.max_output_tokens,
                system=self.instructions,
                tools=self.tool_contract(),
                messages=messages,
                thinking=ThinkingConfigAdaptiveParam(
                    type="adaptive"
                ),
                **kwargs,
        ) as stream:
            return stream.get_final_message()

    @override
    def usage(self, response: Message) -> TokenUsage:
        usage = response.usage

        reasoning_tokens = (
            usage.output_tokens_details.thinking_tokens
            if usage.output_tokens_details is not None
            else None
        )

        return TokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=reasoning_tokens,
            cached_input_tokens=usage.cache_read_input_tokens,
            cache_write_tokens=usage.cache_creation_input_tokens,
            total_tokens=usage.input_tokens + usage.output_tokens,
        )

    @override
    def output_text(self, response: Message) -> str:
        return "".join(
            block.text
            for block in response.content
            if block.type == "text"
        )

    @override
    def tool_call_contract(self, response: Message) -> list[ToolCall]:
        return [
            ToolCall(
                name=block.name,
                args=dict(block.input),
            )
            for block in response.content
            if block.type == "tool_use"
        ]

    @override
    def tool_contract(self) -> list[ToolParam]:
        return [
            ToolParam(
                name=tool_data.name,
                description=tool_data.description,
                input_schema={
                    "type": "object",
                    "properties": tool_data.parameters.properties,
                    "required": tool_data.parameters.required,
                    "additionalProperties": tool_data.parameters.additional_properties
                },
                strict=tool_data.strict
            )
            for tool_data in self.tools.data_mapping.values()
        ]
