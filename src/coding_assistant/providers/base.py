from pathlib import Path
from abc import ABC, abstractmethod

from .schemas import (models_data, ModelData, ProviderId,
                      TokenUsage, ReasoningLevel, QueryRecord, MemoryType, Context)
from ..logger import Logger, QueryLog, LLMToolCallLog, LLMFinalCallLog, ToolCallLog
from ..config import Config
from ..tools.content import Tools, ToolCall, ToolOutput
from ..utils import OutputProtocol

class BaseLLM[ClientT, ContextT: Context](ABC):
    def __init__(
            self,
            instructions: str,
            repo_path: Path,
            config: Config,
            client: ClientT,
            context: ContextT,
            provider: ProviderId
    ):
        self.config = config
        self.client = client
        self.instructions = instructions

        self.model_data, self.reasoning = self._resolve_model(
            provider=provider
        )

        self.tools = Tools(
            repo_path=repo_path,
            blocked_files=config.blocked_files,
            blocked_dirs=config.blocked_dirs
        )

        self.logger = Logger(
            log_path=config.log_path
        )

        self.context = context

    def _resolve_model(
            self,
            provider: ProviderId
    ) -> tuple[ModelData, ReasoningLevel | None]:

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

        if model_data.reasoning.levels:
            reasoning = self.config.reasoning

            if reasoning is None:
                reasoning = model_data.reasoning.default

                if reasoning is None:
                    raise ValueError(
                        f"No default reasoning configured for model {model_data.id}"
                    )

            elif reasoning not in model_data.reasoning.levels:
                raise ValueError(
                    f"{model_data.id} does not support reasoning level {reasoning}"
                )

            return model_data, reasoning

        if self.config.reasoning is not None:
            raise ValueError(
                f"{model_data.id} does not support reasoning"
            )

        return model_data, None

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

    def generate(
            self,
            inputs: str | list[ToolOutput],
            instructions: str,
            memory_type: MemoryType,
    ):
        if memory_type == "context":
            if not isinstance(inputs, str):
                raise TypeError(
                    "Context calls require a query string"
                )

        elif memory_type == "continuation":
            if not isinstance(inputs, list):
                raise TypeError(
                    "Continuation calls require tool outputs"
                )

            if not self.context.can_continue():
                raise ValueError(
                    "Continuation requires a previous response"
                )

        else:
            raise ValueError(
                f"Invalid memory type: {memory_type}"
            )

        return self._generate(
            inputs=inputs,
            instructions=instructions,
            memory_type=memory_type,
        )

    @abstractmethod
    def _generate(
        self,
        inputs: str | list[ToolOutput],
        instructions: str,
        memory_type: MemoryType,
    ):
        ...

    def log(self) -> OutputProtocol:
        return self.logger.log()

    def run(self, query: str) -> str:
        self.context.start_query()

        query_log = QueryLog(query=query)
        query_record = QueryRecord(query=query)

        try:
            response = self.generate(
                inputs=query,
                instructions=self.instructions,
                memory_type="context"
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

                    query_record.completed = True
                    query_record.final_response = output_text

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

                for tool_output in outputs:
                    if (
                        not tool_output.output.is_fail()
                        and tool_output.change_event is not None
                    ):
                        query_record.add_change_event(
                            tool_output.change_event
                        )

                query_log.add_llm_call(LLMToolCallLog(
                    usage=usage,
                    tool_calls=[ToolCallLog(
                        name=call.name,
                        args=call.args,
                        output=tool_output.output
                    ) for call, tool_output in zip(tool_calls, outputs)]
                ))

                response = self.generate(
                    inputs=outputs,
                    instructions=self.instructions,
                    memory_type="continuation"
                )

        finally:
            self.context.add_record(record=query_record)
            query_log.set_query_record(query_record=query_record)

            self.logger.add_query_log(
                query_log=query_log
            )
