from pathlib import Path
from typing import override
import json

from google import genai
from google.genai._gaos.types.interactions import Interaction

from .base import BaseLLM
from coding_assistant.models.schema import TokenUsage, MemoryType, IdContext, Context
from ..config import Config
from ..tools.content import ToolCall, ToolOutput

class GeminiLLM(BaseLLM[genai.Client, IdContext]):
    def __init__(
            self,
            instructions: str,
            repo_path: Path,
            config: Config,
            context: Context | None = None
    ):
        if context is not None:
            context = IdContext(
                query_records=context.query_records
            )

        else:
            context = IdContext()

        super().__init__(
            instructions=instructions,
            repo_path=repo_path,
            config=config,
            provider="google",
            client=genai.Client(),
            context=context
        )

    @override
    def _generate(
            self,
            inputs: str | list[ToolOutput],
            instructions: str,
            memory_type: MemoryType
    ) -> Interaction:
        kwargs = {}

        if self.reasoning is not None:
            kwargs["generation_config"] = {
                "thinking_level": self.reasoning
            }

        if isinstance(inputs, list):
            request_input = [
                self.tool_output_contract(output)
                for output in inputs
            ]
        else:
            request_input = inputs

        if memory_type == "continuation":
            kwargs["previous_interaction_id"] = self.context.last_id

        elif memory_type == "context":
            if self.context.query_records:
                context_text = json.dumps(
                    [
                        record.serialize()
                        for record in self.context.query_records
                    ],
                    ensure_ascii=False,
                )

                request_input = (
                        "Previous session context:\n"
                        + context_text
                        + "\n\nCurrent user query:\n"
                        + request_input
                )

        response = self.client.interactions.create(
            model=self.model_data.id,
            input=request_input,
            system_instruction=instructions,
            tools=self.tool_contract(),
            **kwargs
        )

        self.context.update_id(id_=response.id)
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
                call_id=step.id,
                name=step.name,
                args=dict(step.arguments),
            )
            for step in response.steps
            if step.operation == "function_call"
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
                    )
                }
            ]
        }

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
