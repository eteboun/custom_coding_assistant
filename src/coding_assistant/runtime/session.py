from ..memory.memory import Memory
from ..tools.context import ToolEvent
from ..runtime.logger import Logger, QueryLog, LLMCallLog

from typing import Self
from logging import getLogger

logger = getLogger(__name__)


class QuerySession:
    def __init__(
        self,
        query: str,
        query_logger: Logger,
        memory: Memory | None = None
    ) -> None:
        self.query = query
        self.memory = memory
        self.query_logger = query_logger

        self.query_log = QueryLog(
            query=query
        )

        self.output: str | None = None
        self.loop_completed = False

    def __enter__(self) -> Self:
        if self.memory is not None:
            self.memory.start_query(
                query=self.query
            )

        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> bool:
        cleanup_errors: list[Exception] = []

        try:
            if self.memory is not None:
                self.memory.finish_query(
                    output=self.output,
                    loop_completed=self.loop_completed
                )

                self.query_log.session_final_memory = self.memory.to_log()

        except Exception as error:
            cleanup_errors.append(error)

        try:
            self.query_logger.add_query_log(
                self.query_log
            )
        except Exception as error:
            cleanup_errors.append(error)

        if cleanup_errors or exc_value is not None:
            errors = cleanup_errors + (
                [exc_value]
                if exc_value is not None
                else []
            )

            self.query_log.errors = errors

        if cleanup_errors:
            if exc_value is None:
                if len(cleanup_errors) == 1:
                    raise cleanup_errors[0]

                raise ExceptionGroup(
                    "Failed to close query session.",
                    cleanup_errors,
                )

            for error in cleanup_errors:
                logger.error(
                    "Failed to close query session during exception cleanup.",
                    exc_info=error,
                )

        return False

    def add_event(self, event: ToolEvent) -> None:
        if self.memory is None:
            raise RuntimeError(
                "Memory required for event accumulation"
            )

        self.memory.add_event(event)

    def add_llm_call(self, llm_call: LLMCallLog) -> None:
        self.query_log.add_llm_call(llm_call)

    def context(self) -> str:
        if self.memory is None:
            return self.query

        return self.memory.format_context()

    def complete_loop(self, output: str) -> None:
        self.output = output
        self.loop_completed = True
