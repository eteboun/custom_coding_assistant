from ..memory.memory import ActiveMemory, ToolEvent
from .logger import Logger, QueryLog, LLMCallLog

from typing import Self, Any
from logging import getLogger

logger = getLogger(__name__)


class QuerySession:
    def __init__(
        self,
        query: str,
        memory: ActiveMemory,
        query_logger: Logger,
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
        self.memory.start_session(
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
            self.memory.finish_session(
                output=self.output,
                loop_completed=self.loop_completed,
            )
            self.query_log.session_final_memory = self.memory_log()

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
        self.memory.add_event(event)

    def add_llm_call(self, llm_call: LLMCallLog) -> None:
        self.query_log.add_llm_call(llm_call)

    def memory_log(self) -> dict[str, Any]:
        return self.memory.to_log()

    def context(self) -> str:
        return self.memory.format_context()

    def complete_loop(self, output: str) -> None:
        self.output = output
        self.loop_completed = True
