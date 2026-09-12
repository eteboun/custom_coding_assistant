from pathlib import Path
from typing import override
from pydantic import BaseModel
import json

from google import genai
from google.genai import types
from google.genai._gaos.types.interactions import Interaction

from .base import BaseLLM
from ..ai.schemas import TokenUsage
from ..ai.config import Config
from ..tools.content import ToolCall, ToolOutput

class GeminiLLM(BaseLLM[genai.Client]):
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
            provider="google",
            client=genai.Client()
        )

    def _generate(
            self,
            inputs,
            instructions: str,
            prev_id: str | None = None,
    ) -> Interaction:
        generation_config = {}

        if self.config.reasoning is not None:
            generation_config["thinking_level"] = self.config.reasoning

        return self.client.interactions.create(
            model=self.model_data.id,
            input=inputs,
            system_instruction=instructions,
            tools=self.tool_contract(),
            generation_config=generation_config,
            **(
                {"previous_interaction_id": prev_id}
                if prev_id is not None
                else {}
            ),
        )

    def _parse[T: BaseModel](
            self,
            inputs,
            response_format: type[T],
            instructions: str
    ) -> Interaction:
        return self.client.interactions.create(
            model=self.model_data.id,
            input=inputs,
            system_instruction=instructions,
            response_format={
                "type": "text",
                "mime_type": "application/json",
                "schema": response_format.model_json_schema(),
            },
        )

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
                call_id=step.id,
                name=step.name,
                args=dict(step.arguments),
            )
            for step in response.steps
            if step.type == "function_call"
        ]

    @override
    def tool_output_contract(
            self,
            tool_output: ToolOutput,
    ) -> dict:
        return {
            "type": "function_result",
            "name": tool_output.name,
            "call_id": tool_output.call_id,
            "result": [
                {
                    "type": "text",
                    "text": json.dumps(
                        tool_output.output.serialize()
                    ),
                }
            ],
        }

    @override
    def tool_contract(self) -> list[types.Tool]:
        declarations = [
            types.FunctionDeclaration(
                name=tool.name,
                description=tool.description,
                parameters=tool.parameters.serialize(),
            )
            for tool in self.tools.datas
        ]

        return [
            types.Tool(
                function_declarations=declarations
            )
        ]

    @override
    def initial_call(self, query: str, instructions: str) -> Interaction:
        return self._generate(inputs=query, instructions=instructions)

    @override
    def next_call(
            self,
            outputs: list[ToolOutput],
            response: Interaction,
            instructions: str
    ) -> Interaction:
        return self._generate(
            inputs=[
                self.tool_output_contract(output)
                for output in outputs
            ],
            prev_id=response.id,
            instructions=instructions
        )