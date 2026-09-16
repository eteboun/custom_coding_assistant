from __future__ import annotations

from dataclasses import dataclass, field
from abc import ABC, abstractmethod
from typing import override, Literal

from ..utils import Serializable
from ..tools.content import Tools, ToolEvent

MemoryType = Literal[
    "continuation", "context"
]

@dataclass(frozen=True)
class MutationSummary(Serializable):
    name: str
    summary: str

    def serialize(self) -> dict:
        return {
            "name": self.name,
            "summary": self.summary
        }

@dataclass
class QueryRecord(Serializable):
    query: str
    mutation_summaries: list[MutationSummary] = field(default_factory=list)
    final_response: str | None = None
    completed: bool = False

    def serialize(self) -> dict:
        return {
            "query": self.query,
            "final_response": self.final_response,
            "mutation_summaries": [
                event.serialize()
                for event in self.mutation_summaries
            ]
        }

    def add_mutation(self, mutation_summary: MutationSummary) -> None:
        self.mutation_summaries.append(mutation_summary)

@dataclass
class ShortMemory:
    tools: Tools
    events: list[ToolEvent] = field(default_factory=list)
    pending_mutation: MutationSummary | None = None

    def update(self, event: ToolEvent) -> None:
        if not event.output.mutations:
            self.events.append(event)
            return

        new_events: list[ToolEvent] = []
        affected_files = event.output.files

        for saved_event in self.events:
            if any(
                    file in affected_files
                    for file in saved_event.output.files
            ):
                saved_event.execute(self.tools)
                if saved_event.output.output.is_fail():
                    continue

                new_events.append(saved_event)

            else:
                new_events.append(saved_event)

        self.events = new_events
        self.pending_mutation = MutationSummary(
            name=event.name,
            summary=event.mutation_summary
        )



@dataclass
class LongMemory:
    query_records: list[QueryRecord] = field(default_factory=list)

@dataclass
class Context(ABC):
    query_records: list[QueryRecord] = field(default_factory=list)

    def add_record(self, record: QueryRecord) -> None:
        self.query_records.append(record)

    @abstractmethod
    def start_query(self) -> None:
        ...

    @abstractmethod
    def can_continue(self) -> bool:
        ...

@dataclass
class IdContext(Context):
    last_id: str | None = None

    @override
    def start_query(self) -> None:
        self.last_id = None

    @override
    def can_continue(self) -> bool:
        return self.last_id is not None

    def update_id(self, id_: str) -> None:
        self.last_id = id_

@dataclass
class MessageContext[T](Context):
    messages: list[T] = field(default_factory=list)

    @override
    def start_query(self) -> None:
        self.messages.clear()

    @override
    def can_continue(self) -> bool:
        return bool(self.messages)

    def add_message(self, message: T) -> None:
        self.messages.append(message)