from pathlib import Path
from pydantic import BaseModel

from abc import ABC, abstractmethod

from ..ai.schemas import (models_data, Workflows, WorkflowSelection,
                                         ModelData, ProviderId, TokenUsage, Workflow)
from ..ai.logger import Logger, QueryLog, LLMToolCallLog, LLMFinalCallLog, LLMWorkflowSelectionLog, ToolCallLog
from ..ai.config import Config
from ..tools.content import Tools, ToolCall, ToolOutput
from ..utils import OutputProtocol

class BaseLLM[ClientT](ABC):
    def __init__(
            self,
            instructions: str,
            workflow_instructions: str,
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

        self.workflows = Workflows(
            instructions=workflow_instructions
        )

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
