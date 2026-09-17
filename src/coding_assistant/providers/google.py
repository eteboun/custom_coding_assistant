from pathlib import Path
from typing import override

from google import genai
from google.genai._gaos.types.interactions import Interaction

from .base import BaseLLM

from ..memory.memory import LongMemory
from ..models.schema import TokenUsage
from ..config import Config
from ..tools.context import ToolCall

class GeminiLLM(BaseLLM[genai.Client]):
    def __init__(
            self,
            instructions: str,
            repo_path: Path,
            config: Config,
            long_memory: LongMemory | None = None
    ):
        super().__init__(
            instructions=instructions,
            repo_path=repo_path,
            config=config,
            provider="openai",
            client=genai.Client(),
            long_memory=long_memory
        )

    @override
    def generate(self) -> Interaction:
        kwargs = {}

        if self.reasoning is not None:
            kwargs["generation_config"] = {
                "thinking_level": self.reasoning
            }

        response = self.client.interactions.create(
            model=self.model_data.id,
            input=self.memory.format_context(),
            system_instruction=self.instructions,
            tools=self.tool_contract(),
            **kwargs
        )

        return response

    @override
    def usage(self, response: Interaction) -> TokenUsage:
        usage = response.usage

        return TokenUsage(
            input_tokens=usage.total_input_tokens,
            output_tokens=usage.total_output_tokens,
            reasoning_tokens=usage.total_thought_tokens,
            total_tokens=usage.total_tokens,
            cached_input_tokens=usage.total_cached_tokens
        )

    @override
    def output_text(self, response: Interaction) -> str:
        return response.output_text

    @override
    def tool_call_contract(
            self,
            response: Interaction,
    ) -> list[ToolCall]:
        return [
            ToolCall(
                name=step.name,
                args=dict(step.arguments),
            )
            for step in response.steps
            if step.operation == "function_call"
        ]

    @override
    def tool_contract(self) -> list[dict]:
        return [
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": tool.parameters.properties,
                    "required": tool.parameters.required
                }
            }
            for tool in self.tools.datas
        ]
