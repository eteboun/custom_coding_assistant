from pathlib import Path
from abc import ABC, abstractmethod

from coding_assistant.memory.memory import ActiveMemory, ShortMemory, LongMemory, ToolEvent

from ..models.operations import resolve_reasoning, resolve_model
from ..models.schema import ProviderId, TokenUsage, ReasoningLevel

from ..config import Config

from ..utils import MaxIterationsError

from ..tools.content import Tools
from ..tools.executor import Executor
from ..tools.context import ToolCall

from ..logger import QueryLog, Logger, LLMToolEventLog, LLMFinalCallLog

class BaseLLM[ClientT](ABC):
    def __init__(
        self,
        instructions: str,
        repo_path: Path,
        config: Config,
        client: ClientT,
        provider: ProviderId,
        *,
        long_memory: LongMemory | None,
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

        self.executor = Executor(
            tools=self.tools
        )

        self.memory = ActiveMemory(
            executor=self.executor,
            long_memory=(
                long_memory
                if long_memory is not None
                else LongMemory()
            ),
            short_memory=ShortMemory()
        )

        self.logger = Logger(
            log_path=config.log_path
        )


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
    def tool_call_contract(self, response) -> list[ToolCall]:
        ...

    @abstractmethod
    def tool_contract(self):
        ...

    @abstractmethod
    def generate(self):
        ...

    def log(self) -> str:
        return self.logger.log()

    def run(self, query: str) -> str:
        self.memory.start_session(query=query)

        query_log = QueryLog(
            query=query,
            initial_memory=self.memory.to_log()
        )

        output_text: str | None = None
        completed = False

        try:
            response = self.generate()

            for i in range(self.config.max_iters):
                usage = self.usage(response=response)
                tool_calls = self.tool_call_contract(response)

                if not tool_calls:
                    output_text = self.output_text(response)
                    completed = True

                    query_log.add_llm_call(LLMFinalCallLog(
                        usage=usage,
                        response=output_text
                    ))

                    return output_text

                if i == self.config.max_iters - 1:
                    raise MaxIterationsError(
                        f"Maximum iteration limit reached: "
                        f"{self.config.max_iters}"
                    )

                tool_outputs = [
                    self.executor.execute_call(call=call)
                    for call in tool_calls
                ]

                events: list[ToolEvent] = []
                for tool_call, tool_output in zip(
                        tool_calls, tool_outputs
                ):
                    if tool_output.is_fail():
                        events.append(ToolEvent(
                            call=tool_call,
                            output=tool_output
                        ))
                        continue

                    metadata = self.tools.data_mapping[
                        tool_call.name
                    ].metadata

                    events.append(ToolEvent(
                        call=tool_call,
                        output=tool_output,
                        update_when=metadata.update_when,
                        update_scope=metadata.update_scope
                    ))

                for event in events:
                    self.memory.add_event(event)

                query_log.add_llm_call(LLMToolEventLog(
                    usage=usage,
                    memory=self.memory.to_log(),
                    events=[
                        event.to_log()
                        for event in events
                    ]
                ))

                response = self.generate()

        finally:
            self.memory.finish_session(
                output=output_text,
                completed=completed
            )

            query_log.final_memory = self.memory.to_log()

            self.logger.add_query_log(
                query_log=query_log
            )
