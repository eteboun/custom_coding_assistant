from typing import Literal, Generic, TypeVar, override
from pathlib import Path
import json

from pydantic import BaseModel
from abc import ABC, abstractmethod

from openai import OpenAI
from openai.types.shared_params import Reasoning
from openai.types.responses import Response
from openai.types.responses import FunctionToolParam

from google import genai
from google.genai import types
from google.genai._gaos.types.interactions import Interaction

from anthropic import Anthropic
from anthropic.types import (ToolParam, MessageParam,
                             ThinkingConfigAdaptiveParam, OutputConfigParam,
                             Message, ToolResultBlockParam)

from coding_assistant.config import config_reasoning_levels
from coding_assistant.tools.content import Tools, ToolCall, ToolOutput

ClientT = TypeVar("ClientT")

_models_json = Path(__file__).resolve().parent / "llm_data" / "models.json"
_providers_json = Path(__file__).resolve().parent / "llm_data" / "providers.json"

ProviderId = Literal[
    "openai",
    "anthropic",
    "google",
]

ReasoningLevel = Literal[
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
]

class ModelPricing(BaseModel):
    input: float
    output: float

    cached_input: float | None = None

    cache_write_5m: float | None = None
    cache_write_1h: float | None = None


class AboveThresholdPricing(BaseModel):
    input: float
    output: float


class ModelPricingRules(BaseModel):
    long_context_threshold: int | None = None

    above_threshold_input_multiplier: float | None = None
    above_threshold_output_multiplier: float | None = None

    above_threshold: AboveThresholdPricing | None = None


class ModelData(BaseModel):
    id: str
    provider: ProviderId

    context_window: int
    max_output_tokens: int

    reasoning_levels: list[ReasoningLevel] | None = None

    pricing: ModelPricing
    pricing_rules: ModelPricingRules | None = None


class ModelsData(BaseModel):
    currency: Literal["USD"]
    pricing_unit: Literal["per_1m_tokens"]

    models: dict[str, ModelData]

def load_models() -> ModelsData:
    with open(_models_json) as f:
        return ModelsData.model_validate_json(
            f.read()
        )

models_data = load_models()

class BaseLLM(ABC, Generic[ClientT]):
    def __init__(
            self,
            model_name: str,
            instructions: str,
            max_iters: int,
            reasoning: config_reasoning_levels | None,
            client: ClientT,
            tools: Tools,
            model_data: ModelData
    ):
        if max_iters <= 0:
            raise ValueError("max_iters must be a positive integer")

        self.model_name = model_name
        self.instructions = instructions
        self.max_iters = max_iters
        self.client = client
        self.tools = tools

        self.model_data = model_data
        self.reasoning = reasoning

    @staticmethod
    def validate_datas(model: str,
                       provider: ProviderId,
                       reasoning: config_reasoning_levels | None
                       ) -> tuple[ModelData, config_reasoning_levels | None]:

        model_data = models_data.models.get(
            model
        )

        if model_data is None:
            raise ValueError(
                f"Model {model} is not recognized"
            )

        if model_data.provider != provider:
            raise ValueError(
                f"Model {model} does not belong to {provider}"
            )

        reasoning_levels = model_data.reasoning_levels

        if reasoning_levels:
            if reasoning is None:
                raise ValueError(
                    f"reasoning is required for {model}"
                )

            if reasoning not in reasoning_levels:
                raise ValueError(
                    f"{model} does not support reasoning level {reasoning}"
                )

        elif reasoning is not None:
            raise ValueError(
                f"{model} does not support configurable reasoning"
            )

        return model_data, reasoning

    @abstractmethod
    def output_text(self, response) -> str:
        ...

    @abstractmethod
    def tool_call_contract(self, response) -> list[ToolCall]:
        ...

    @abstractmethod
    def tool_output_contract(self, tool_output: ToolOutput):
        ...

    @abstractmethod
    def tool_contract(self):
        ...

    @abstractmethod
    def initial_call(self, query: str):
        ...

    @abstractmethod
    def next_call(self, response, outputs):
        ...

    def run(self, query: str) -> str:
        response = self.initial_call(query)

        for _ in range(self.max_iters):
            tool_calls = self.tool_call_contract(response)

            if not tool_calls:
                return self.output_text(response)

            response = self.next_call(
                response=response,
                outputs=[
                    tool_call.execute(self.tools)
                    for tool_call in tool_calls
                ],
            )

        raise RuntimeError(
            f"Maximum iteration limit reached: {self.max_iters}"
        )

class OpenAILLM(BaseLLM[OpenAI]):
    def __init__(
            self,
            model_name: str,
            instructions: str,
            max_iters: int,
            reasoning: config_reasoning_levels | None,
            tools: Tools,
    ):
        model_data, reasoning = self.validate_datas(
            model=model_name,
            reasoning=reasoning,
            provider="openai"
        )

        super().__init__(
            model_name=model_name,
            instructions=instructions,
            max_iters=max_iters,
            reasoning=reasoning,
            client=OpenAI(),
            tools=tools,
            model_data=model_data,
        )

    def _generate(
        self,
        inputs,
        prev_id: str | None = None,
    ) -> Response:
        kwargs = {}

        if self.reasoning is not None:
            kwargs["reasoning"] = Reasoning(
                effort=self.reasoning
            )

        if prev_id is not None:
            kwargs["previous_response_id"] = prev_id

        return self.client.responses.create(
            model=self.model_data.id,
            instructions=self.instructions,
            input=inputs,
            tools=self.tool_contract(),
            **kwargs,
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
                args=json.loads(item.arguments),
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
    def initial_call(self, query: str) -> Response:
        return self._generate(query)

    @override
    def next_call(
            self,
            outputs: list[ToolOutput],
            response: Response,
    ) -> Response:
        return self._generate(
            inputs=[
                self.tool_output_contract(output)
                for output in outputs
            ],
            prev_id=response.id
        )

class GeminiLLM(BaseLLM[genai.Client]):
    def __init__(
            self,
            model_name: str,
            instructions: str,
            max_iters: int,
            reasoning: config_reasoning_levels | None,
            tools: Tools,
    ):
        model_data, reasoning = self.validate_datas(
            model=model_name,
            reasoning=reasoning,
            provider="google"
        )

        super().__init__(
            model_name=model_name,
            instructions=instructions,
            max_iters=max_iters,
            reasoning=reasoning,
            client=genai.Client(),
            tools=tools,
            model_data=model_data,
        )

    def _generate(
            self,
            inputs,
            prev_id: str | None = None,
    ) -> Interaction:
        generation_config = {}

        if self.reasoning is not None:
            generation_config["thinking_level"] = self.reasoning

        return self.client.interactions.create(
            model=self.model_data.id,
            input=inputs,
            system_instruction=self.instructions,
            tools=self.tool_contract(),
            generation_config=generation_config,
            **(
                {"previous_interaction_id": prev_id}
                if prev_id is not None
                else {}
            ),
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
    def initial_call(self, query: str) -> Interaction:
        return self._generate(query)

    @override
    def next_call(
            self,
            outputs: list[ToolOutput],
            response: Interaction,
    ) -> Interaction:
        return self._generate(
            inputs=[
                self.tool_output_contract(output)
                for output in outputs
            ],
            prev_id=response.id
        )

class AnthropicLLM(BaseLLM[Anthropic]):
    def __init__(
            self,
            model_name: str,
            instructions: str,
            max_iters: int,
            reasoning: config_reasoning_levels | None,
            tools: Tools,
    ):
        model_data, reasoning = self.validate_datas(
            model=model_name,
            reasoning=reasoning,
            provider="anthropic"
        )

        super().__init__(
            model_name=model_name,
            instructions=instructions,
            max_iters=max_iters,
            reasoning=reasoning,
            client=Anthropic(),
            tools=tools,
            model_data=model_data,
        )

        self.messages: list[MessageParam] = []

    def _generate(
            self,
            inputs: list[MessageParam],
    ) -> Message:
        kwargs = {}

        if self.reasoning is not None:
            kwargs["output_config"] = OutputConfigParam(
                        effort=self.reasoning
                    )

        return self.client.messages.create(
            model=self.model_data.id,
            max_tokens=self.model_data.max_output_tokens,
            system=self.instructions,
            tools=self.tool_contract(),
            messages=inputs,
            thinking=ThinkingConfigAdaptiveParam(
                type="adaptive"
            ),
            **kwargs
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
    def initial_call(self, query: str) -> Message:
        message: MessageParam = {
                "role": "user",
                "content": query,
            }

        self.messages.append(message)
        return self._generate([message])

    @override
    def next_call(
            self,
            outputs: list[ToolOutput],
            response: Message
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

        return self._generate(self.messages)