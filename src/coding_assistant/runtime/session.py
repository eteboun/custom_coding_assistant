from ..memory.memory import Memory
from ..memory.schema import QueryRecord
from ..errors import MaxIterationsError
from ..tools.context import ToolEvent
from ..runtime.logger import Logger, QueryLog, LLMCallLog

from typing import Self
from datetime import timedelta
from logging import getLogger
from time import perf_counter

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
        self.query_log.model_id = query_logger.model_data.id
        self.query_record = QueryRecord(
            query=query, loop_completed=False, final_response=None,
        )

        self.output: str | None = None
        self.loop_completed = False
        self.timedelta = timedelta()
        self._started_at: float | None = None
        self.memory_start_index = 0

    def __enter__(self) -> Self:
        self._started_at = perf_counter()
        if self.memory is not None:
            self.memory_start_index = len(self.memory.elements)
            self.memory.add_query(
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
                if self.output is not None:
                    self.memory.add_output_text(self.output)

                self.query_record.loop_completed = self.loop_completed
                self.query_record.final_response = self.output
                self.query_record.stop_reason = (
                    'max_iterations' if isinstance(exc_value, MaxIterationsError)
                    else 'error' if exc_value is not None else None
                )
                self.memory.add_query_record(self.query_record)

                self.query_log.final_memory = self.memory.to_log()

        except Exception as error:
            cleanup_errors.append(error)

        try:
            if self._started_at is not None:
                self.timedelta = timedelta(
                    seconds=perf_counter() - self._started_at
                )
                self.query_log.timedelta = self.timedelta
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
        if event.output.mutations:
            self.query_record.add_mutation_event({
                'name': event.call.name,
                'mutations': [mutation.to_log() for mutation in event.output.mutations],
                'outcome': {
                    'status': event.output.status,
                    'message': event.output.message,
                },
            })

    def add_llm_call(self, llm_call: LLMCallLog) -> None:
        self.query_log.add_llm_call(llm_call)

    def context(self) -> str:
        if self.memory is None:
            return self.query

        return self.memory.format_context()

    def complete_loop(self, output: str) -> None:
        self.output = output
        self.loop_completed = True
