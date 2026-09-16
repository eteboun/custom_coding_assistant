from pathlib import Path
from abc import ABC, abstractmethod

from .utils import resolve_reasoning, resolve_model
from .schemas import (ProviderId, TokenUsage, ReasoningLevel,
                      QueryRecord, MemoryType, Context, Mutation)
from ..logger import Logger, QueryLog, LLMToolEventLog, LLMFinalCallLog, ToolEventLog
from ..config import Config
from ..tools.content import Tools, ToolEvent
from ..tools.schemas import ToolOutput
from ..utils import OutputProtocol, MaxIterationsError

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

        self.model_data = resolve_model(
            model_name=config.model_name,
            provider=provider
        )

        self.reasoning = resolve_reasoning(
            model_data=self.model_data,
            reasoning=config.reasoning
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

    def update_reasoning(self, reasoning: ReasoningLevel | None) -> None:
        reasoning = resolve_reasoning(
            model_data=self.model_data,
            reasoning=reasoning
        )

        self.reasoning = reasoning

    @abstractmethod
    def usage(self, response) -> TokenUsage:
        ...

    @abstractmethod
    def output_text(self, response) -> str:
        ...

    @abstractmethod
    def tool_event_contract(self, response) -> list[ToolEvent]:
        ...

    @abstractmethod
    def tool_output_contract(self, tool_output: ToolOutput):
        ...

    @abstractmethod
    def tool_contract(self):
        ...

    def execute_tool_events(
            self,
            events: list[ToolEvent]
    ) -> list[ToolOutput]:
        return [
            event.execute(self.tools)
            for event in events
        ]

    @staticmethod
    def create_llm_tool_event_log(
            events: list[ToolEvent],
            usage: TokenUsage
    ) -> LLMToolEventLog:
        tool_events: list[ToolEventLog] = []
        for event in events:

            tool_events.append(ToolEventLog(
                name=event.name,
                args=event.args,
                output=event.output.output
            ))

        return LLMToolEventLog(
            events=tool_events,
            usage=usage
        )

    @staticmethod
    def save_mutations(
            query_record: QueryRecord,
            events: list[ToolEvent]
    ) -> None:
        for event in events:
            event_output = event.output

            if (
                    not event_output.output.is_fail()
                    and event_output.mutation
            ):
                query_record.add_mutation(Mutation(
                    name=event.name,
                    summary=event.mutation_summary
                ))

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
                tool_events = self.tool_event_contract(response)
                usage = self.usage(response=response)

                if not tool_events:
                    output_text = self.output_text(response)

                    query_log.add_llm_call(LLMFinalCallLog(
                        usage=usage,
                        response=output_text
                    ))

                    query_record.completed = True
                    query_record.final_response = output_text

                    return output_text

                if i == self.config.max_iters - 1:
                    query_log.add_llm_call(self.create_llm_tool_event_log(
                        events=tool_events,
                        usage=usage
                    ))
                    raise MaxIterationsError(
                        f"Maximum iteration limit reached: {self.config.max_iters}"
                    )

                outputs = self.execute_tool_events(tool_events)

                self.save_mutations(
                    query_record=query_record,
                    events=tool_events
                )

                query_log.add_llm_call(self.create_llm_tool_event_log(
                    events=tool_events,
                    usage=usage
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
