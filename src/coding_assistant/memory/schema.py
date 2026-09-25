from dataclasses import dataclass, field
from typing import Any, Self

from ..tools.context import LearningMetadata, Mutation, ToolEvent
from ..utils import LogElement, ContextElement, FormattableContext, format_context_structure

@dataclass(frozen=True)
class MutationSummary(LogElement, ContextElement):
    name: str
    summary: str
    mutations: tuple[Mutation, ...]
    outcome: dict[str, Any]

    @classmethod
    def from_event(cls, event: ToolEvent) -> Self:
        assert event.call.mutation_summary is not None

        output = event.output
        return cls(
            name=event.call.name,
            summary=event.call.mutation_summary,
            mutations=output.mutations,
            outcome={
                "status": output.status,
                "content": output.to_context()["content"],
                "message": output.message,
            },
        )

    def to_log(self) -> dict:
        return {
            "name": self.name,
            "summary": self.summary,
            "mutations": [mutation.to_log() for mutation in self.mutations],
            "outcome": self.outcome,
        }

    def to_context(self):
        return {
            "name": self.name,
            "summary": self.summary,
            "mutations": [mutation.to_log() for mutation in self.mutations],
            "outcome": self.outcome,
        }

@dataclass
class QueryRecord(LogElement, ContextElement):
    query: str
    loop_completed: bool
    final_response: str | None
    mutation_summaries: list[MutationSummary]

    def to_log(self) -> dict:
        return {
            "query": self.query,
            "final_response": self.final_response,
            "mutation_summaries": [
                mutation.to_log()
                for mutation in self.mutation_summaries
            ],
            "loop_completed": self.loop_completed
        }

    def to_context(self) -> dict:
        return {
            "query": self.query,
            "final_response": self.final_response,
            "mutation_summaries": [
                mutation.to_context()
                for mutation in self.mutation_summaries
            ]
        }

    def add_mutation(self, mutation_summary: MutationSummary) -> None:
        self.mutation_summaries.append(mutation_summary)

@dataclass(frozen=True)
class PersistentLearning(LogElement, ContextElement):
    tool: str
    message: str
    key: str

    def to_log(self) -> dict:
        return {
            "tool": self.tool,
            "message": self.message,
            "key": self.key
        }

    def to_context(self) -> dict:
        return {
            "tool": self.tool,
            "message": self.message
        }


@dataclass(frozen=True)
class Learning(LogElement, ContextElement):
    tool: str
    args: dict
    message: str
    metadata: LearningMetadata | None = None

    def to_log(self) -> dict:
        return {
            "tool": self.tool,
            "args": self.args,
            "message": self.message,
            "metadata": (
                self.metadata.to_log()
                if self.metadata is not None
                else None
            )
        }

    def to_context(self) -> dict:
        return {
            "tool": self.tool,
            "args": self.args,
            "message": self.message
        }

    def to_persistent(self) -> PersistentLearning:
        if self.metadata is None or not self.metadata.persistent:
            raise ValueError(
                "Transient learning cannot be persisted."
            )

        if self.metadata.key is None:
            raise ValueError(
                "Persistent learning requires a key."
            )

        return PersistentLearning(
            tool=self.tool,
            message=self.message,
            key=self.metadata.key,
        )


@dataclass
class LongMemory(LogElement, FormattableContext):
    query_records: list[QueryRecord] = field(default_factory=list)
    learnings: list[PersistentLearning] = field(default_factory=list)

    def to_log(self) -> dict:
        return {
            "query_records": [
                record.to_log()
                for record in self.query_records
            ],
            "learnings": [
                learning.to_log()
                for learning in self.learnings
            ]
        }

    def format_context(self) -> str:
        sections: list[str] = []

        if self.query_records:
            sections.append(
                format_context_structure(
                    tag="query_records",
                    structure=self.query_records,
                )
            )

        if self.learnings:
            sections.append(
                format_context_structure(
                    tag="persistent_learnings",
                    structure=self.learnings,
                )
            )

        return "\n\n".join(sections)

    def add_learning(self, learning: PersistentLearning) -> None:
        if any(
            saved.key == learning.key
            for saved in self.learnings
        ):
            return

        self.learnings.append(learning)

@dataclass
class ShortMemory(LogElement, FormattableContext):
    events: list[ToolEvent] = field(default_factory=list)
    learnings: list[Learning] = field(default_factory=list)
    pending_mutations: list[MutationSummary] = field(default_factory=list)

    def to_log(self) -> dict:
        return {
            "events": [
                event.to_log()
                for event in self.events
            ],
            "learnings": [
                learning.to_log()
                for learning in self.learnings
            ],
            "pending_mutations": [
                mutation.to_log()
                for mutation in self.pending_mutations
            ]
        }

    def format_context(self) -> str:
        sections: list[str] = []

        if self.pending_mutations:
            sections.append(
                format_context_structure(
                    tag="current_mutations",
                    structure=self.pending_mutations,
                )
            )

        if self.learnings:
            sections.append(
                format_context_structure(
                    tag="current_learnings",
                    structure=self.learnings,
                )
            )

        if self.events:
            sections.append(
                format_context_structure(
                    tag="current_tool_context",
                    structure=self.events,
                )
            )

        return "\n\n".join(sections)

@dataclass
class IntermediateMemory(LogElement, FormattableContext):
    learnings: list[PersistentLearning] = field(default_factory=list)
    mutations: list[MutationSummary] = field(default_factory=list)

    def to_log(self) -> dict:
        return {
            "learnings": [
                learning.to_log()
                for learning in self.learnings
            ],
            "pending_mutations": [
                mutation.to_log()
                for mutation in self.mutations
            ]
        }

    def format_context(self) -> str:
        sections: list[str] = []

        if self.mutations:
            sections.append(
                format_context_structure(
                    tag="mutations",
                    structure=self.mutations,
                )
            )

        if self.learnings:
            sections.append(
                format_context_structure(
                    tag="learnings",
                    structure=self.learnings,
                )
            )

        return "\n\n".join(sections)
