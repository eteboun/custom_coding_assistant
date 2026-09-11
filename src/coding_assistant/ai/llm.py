from pathlib import Path
from typing import override
from pydantic import BaseModel
import json

from abc import ABC, abstractmethod

from openai import OpenAI
from openai.types.shared_params import Reasoning
from openai.types.responses import Response, ParsedResponse
from openai.types.responses import FunctionToolParam

from google import genai
from google.genai import types
from google.genai._gaos.types.interactions import Interaction

from anthropic import Anthropic
from anthropic.types import (ToolParam, MessageParam,
                             ThinkingConfigAdaptiveParam, OutputConfigParam,
                             Message, ToolResultBlockParam, ParsedMessage)

from .schemas import (models_data, workflows, WorkflowSelection,
                      ModelData, ProviderId, TokenUsage, Workflow)
from .logger import Logger, QueryLog, LLMToolCallLog, LLMFinalCallLog, LLMWorkflowSelectionLog, ToolCallLog
from .config import Config
from ..tools.content import Tools, ToolCall, ToolOutput
from ..utils import OutputProtocol

class BaseLLM[ClientT](ABC):
    def __init__(
            self,
            instructions: str,
            repo_path: Path,
            config: Config,
            client: ClientT,
            provider: ProviderId
    ):
        self.config = config
        self.client = client
        self.instructions = instructions

        self.model_data = self._resolve_model(
            provider=provider
        )

        self.tools = Tools(
            repo_path=repo_path,
            blocked_files=config.blocked_files,
            blocked_dirs=config.blocked_dirs
        )

        self.workflows = workflows

        self.logger = Logger(
            log_path=config.log_path
        )

    def _resolve_model(
            self,
            provider: ProviderId,
        ) -> ModelData:

        model_data = models_data.models.get(
            self.config.model_name
        )

        if model_data is None:
            raise ValueError(
                f"Model {self.config.model_name} is not recognized"
            )

        if model_data.provider != provider:
            raise ValueError(
                f"Model {self.config.model_name} does not belong to {provider}"
            )

        reasoning_levels = model_data.reasoning_levels

        if reasoning_levels:
            if self.config.reasoning is None:
                raise ValueError(
                    f"reasoning is required for {self.config.model_name}"
                )

            if self.config.reasoning not in reasoning_levels:
                raise ValueError(
                    f"{self.config.model_name} does not support reasoning level {self.config.reasoning}"
                )

        elif self.config.reasoning is not None:
            raise ValueError(
                f"{self.config.model_name} does not support configurable reasoning"
            )

        return model_data

    @abstractmethod
    def extract_workflow[T: BaseModel](
            self,
            inputs,
            response_format: type[T]
    ) -> tuple[Workflow, WorkflowSelection, TokenUsage]:
        ...

    @abstractmethod
    def usage(self, response) -> TokenUsage:
        ...

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
    def initial_call(self, query: str, instructions: str):
        ...

    @abstractmethod
    def next_call(self, response, outputs, instructions: str):
        ...

    def build_instructions(self, workflow: Workflow) -> str:
        return f"""
        {self.instructions}
        
        {workflow.content}
        """

    def log(self) -> OutputProtocol:
        return self.logger.log()

    def run(self, query: str) -> str:
        query_log = QueryLog(query=query)

        try:
            workflow, selection, usage = self.extract_workflow(
                inputs=query,
                response_format=WorkflowSelection
            )

            query_log.add_llm_call(LLMWorkflowSelectionLog(
                usage=usage,
                selection=selection
            ))

            instructions = self.build_instructions(
                workflow=workflow
            )

            response = self.initial_call(
                query=query,
                instructions=instructions
            )

            for i in range(self.config.max_iters):
                tool_calls = self.tool_call_contract(response)
                usage = self.usage(response=response)

                if not tool_calls:
                    output_text = self.output_text(response)

                    query_log.add_llm_call(LLMFinalCallLog(
                        usage=usage,
                        response=output_text
                    ))
                    return output_text

                if i == self.config.max_iters - 1:
                    query_log.add_llm_call(LLMToolCallLog(
                        usage=usage,
                        tool_calls=[ToolCallLog(
                            name=call.name,
                            args=call.args
                        ) for call in tool_calls]
                    ))
                    raise RuntimeError(
                        f"Maximum iteration limit reached: {self.config.max_iters}"
                    )

                outputs = [
                        tool_call.execute(self.tools)
                        for tool_call in tool_calls
                    ]

                query_log.add_llm_call(LLMToolCallLog(
                    usage=usage,
                    tool_calls=[ToolCallLog(
                        name=call.name,
                        args=call.args,
                        output=tool_output.output
                    ) for call, tool_output in zip(tool_calls, outputs)]
                ))

                response = self.next_call(
                    response=response,
                    outputs=outputs,
                    instructions=instructions
                )

        finally:
            self.logger.add_query_log(
                query_log=query_log
            )

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
    def extract_workflow[T: BaseModel](
            self,
            inputs,
            response_format: type[T]
    ) -> tuple[Workflow, WorkflowSelection, TokenUsage]:

        response = self._parse(
            inputs=inputs,
            response_format=response_format,
            instructions=self.workflows.instructions
        )

        selection = response.output_parsed

        return self.workflows.from_selection(
            selection=selection
        ), selection, self.usage(response=response)

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
    def extract_workflow[T: BaseModel](
            self,
            inputs,
            response_format: type[T]
    ) -> tuple[Workflow, WorkflowSelection, TokenUsage]:
        response = self._parse(
            inputs=inputs,
            response_format=response_format,
            instructions=self.workflows.instructions
        )

        selection = WorkflowSelection.model_validate_json(
            response.output_text
        )

        return self.workflows.from_selection(
            selection=selection
        ), selection, self.usage(response=response)

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

    def _parse[T: BaseModel](
            self,
            inputs,
            response_format: type[T],
            instructions: str,
    ) -> ParsedMessage[T]:
        messages: list[MessageParam] = [
            {"role": "user", "content": inputs}
        ]

        return self.client.messages.parse(
            model=self.model_data.id,
            max_tokens=100,
            system=instructions,
            messages=messages,
            output_format=response_format,
        )

    @override
    def extract_workflow[T: BaseModel](
            self,
            inputs,
            response_format: type[T]
    ) -> tuple[Workflow, WorkflowSelection, TokenUsage]:
        response = self._parse(
            inputs=inputs,
            response_format=response_format,
            instructions=self.workflows.instructions
        )

        selection: WorkflowSelection = response.parsed_output

        return self.workflows.from_selection(
            selection=selection
        ), selection, self.usage(response=response)

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

def create_llm(
        instructions: str,
        repo_path: Path,
        config: Config
) -> BaseLLM:
    model_data = models_data.models.get(config.model_name)

    if model_data is None:
        raise ValueError(
            f"Model {config.model_name} not found."
        )

    match model_data.provider:
        case "openai":
            return OpenAILLM(
                instructions=instructions,
                repo_path=repo_path,
                config=config,
            )

        case "google":
            return GeminiLLM(
                instructions=instructions,
                repo_path=repo_path,
                config=config,
            )

        case "anthropic":
            return AnthropicLLM(
                instructions=instructions,
                repo_path=repo_path,
                config=config,
            )

        case _:
            raise ValueError(
                f"Unknown provider {model_data.provider}"
            )
