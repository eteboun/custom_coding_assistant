from pathlib import Path
from typing import override
import json

from anthropic import Anthropic
from anthropic.types import (ToolParam, MessageParam,
                             ThinkingConfigAdaptiveParam, OutputConfigParam,
                             Message, ToolResultBlockParam)

from .base import BaseLLM
from ..ai.schemas import TokenUsage
from ..ai.config import Config
from ..tools.content import ToolCall, ToolOutput

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

        self.messages: list[MessageParam] = []

    def _generate(
            self,
            inputs: list[MessageParam],
            instructions: str,
    ) -> Message:
        kwargs = {}

        if self.config.reasoning is not None:
            kwargs["output_config"] = OutputConfigParam(
                        effort=self.config.reasoning
                    )

        return self.client.messages.create(
            model=self.model_data.id,
            max_tokens=self.model_data.max_output_tokens,
            system=instructions,
            tools=self.tool_contract(),
            messages=inputs,
            thinking=ThinkingConfigAdaptiveParam(
                type="adaptive"
            ),
            **kwargs
        )

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
                call_id=block.id,
                name=block.name,
                args=dict(block.input),
            )
            for block in response.content
            if block.type == "tool_use"
        ]

    @override
    def tool_output_contract(self, tool_output: ToolOutput) -> ToolResultBlockParam:
        return ToolResultBlockParam(
            type="tool_result",
            tool_use_id=tool_output.call_id,
            content=json.dumps(
                tool_output.output.serialize()
            )
        )

    @override
    def tool_contract(self) -> list[ToolParam]:
        return [
            ToolParam(
                name=tool.name,
                description=tool.description,
                input_schema=tool.parameters.serialize(),
            )
            for tool in self.tools.datas
        ]

    @override
    def initial_call(self, query: str, instructions: str) -> Message:
        message: MessageParam = {
                "role": "user",
                "content": query,
            }

        self.messages.append(message)
        return self._generate([message], instructions=instructions)

    @override
    def next_call(
            self,
            outputs: list[ToolOutput],
            response: Message,
            instructions: str
    ) -> Message:
        self.messages.append({
            "role": "assistant",
            "content": response.content,
        })

        self.messages.append({
            "role": "user",
            "content": [
                self.tool_output_contract(output)
                for output in outputs
            ],
        })

        return self._generate(self.messages, instructions=instructions)
