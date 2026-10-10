from dataclasses import dataclass, field
from typing import Any

from ..tools.context import ToolEvent
from ..interfaces import LogElement, ContextElement


class MemoryElement(LogElement, ContextElement):
    """One item in the ordered memory stream."""


@dataclass(frozen=True)
class QueryElement(MemoryElement):
    query: str

    def to_log(self) -> dict:
        return {'type': 'query', 'query': self.query}

    def to_context(self) -> dict:
        return self.to_log()


@dataclass(frozen=True)
class ToolEventElement(MemoryElement):
    event: ToolEvent

    def to_log(self) -> dict:
        return {'type': 'tool_event', **self.event.to_log()}

    def to_context(self) -> dict:
        return {'type': 'tool_event', **self.event.to_context()}


@dataclass(frozen=True)
class OutputTextElement(MemoryElement):
    text: str

    def to_log(self) -> dict:
        return {'type': 'output_text', 'text': self.text}

    def to_context(self) -> dict:
        return self.to_log()


@dataclass
class QueryRecord(MemoryElement):
    query: str
    loop_completed: bool
    final_response: str | None
    mutation_summaries: list[dict[str, Any]] = field(default_factory=list)
    stop_reason: str | None = None

    def to_log(self) -> dict:
        return {
            "query": self.query,
            "final_response": self.final_response,
            "mutation_summaries": [
                mutation
                for mutation in self.mutation_summaries
            ],
            "loop_completed": self.loop_completed,
            "stop_reason": self.stop_reason,
        }

    def to_context(self) -> dict:
        return {
            "type": "query_record",
            "query": self.query,
            "loop_completed": self.loop_completed,
            "stop_reason": self.stop_reason,
            "final_response": self.final_response,
            "mutation_summaries": [
                mutation
                for mutation in self.mutation_summaries
            ]
        }

    def add_mutation(self, mutation_summary: dict[str, Any]) -> None:
        self.mutation_summaries.append(mutation_summary)
