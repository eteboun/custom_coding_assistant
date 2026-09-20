import json
from dataclasses import dataclass, field

from ..tools.api import ToolsAPI
from ..tools.context import (ToolCall, ToolOutput, UpdateScope,
                                            Operation, Mutation, Invalidation, LearningMetadata)
from ..utils import LogElement, ContextElement

@dataclass(frozen=True)
class MutationSummary(LogElement, ContextElement):
    name: str
    summary: str

    def to_log(self) -> dict:
        return {
            "name": self.name,
            "summary": self.summary
        }

    def to_context(self):
        return {
            "name": self.name,
            "summary": self.summary
        }

@dataclass
class QueryRecord(LogElement, ContextElement):
    query: str
    final_response: str
    loop_completed: bool
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

@dataclass
class ToolEvent(LogElement, ContextElement):
    call: ToolCall
    output: ToolOutput

    update_when: dict[Operation, Invalidation] | None = None
    update_scope: UpdateScope | None = None

    def is_fail(self) -> bool:
        return self.output.output.is_fail()

    def to_log(self) -> dict:
        update_when = {
                op.value: inv.value
                for op, inv in self.update_when.items()
            } if self.update_when is not None else None

        update_scope = (
            self.update_scope.value
            if self.update_scope is not None
            else None
        )

        return {
            "call": self.call.to_log(),
            "output": self.output.to_log(),
            "update_when": update_when,
            "update_scope": update_scope
        }

    def to_context(self):
        return {
            "call": self.call.to_context(),
            "output": self.output.to_context()
        }


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
class LongMemory(LogElement):
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

    def add_learning(self, learning: PersistentLearning) -> None:
        if any(
            saved.key == learning.key
            for saved in self.learnings
        ):
            return

        self.learnings.append(learning)

@dataclass
class ShortMemory(LogElement):
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


@dataclass
class ActiveMemory(LogElement):
    tools_api: ToolsAPI
    short_memory: ShortMemory
    long_memory: LongMemory
    current_query: str | None = None

    def to_log(self) -> dict:
        return {
            "short_memory": self.short_memory.to_log(),
            "long_memory": self.long_memory.to_log(),
            "context": self.format_context()
        }

    @staticmethod
    def _get_invalidation(
            update_when: dict[Operation, Invalidation],
            update_scope: UpdateScope,
            mutations: tuple[Mutation, ...],
            files: tuple[str, ...],
    ) -> Invalidation | None:
        result: Invalidation | None = None

        for mutation in mutations:
            invalidation = update_when.get(mutation.type)

            if invalidation is None:
                continue

            applies = (
                    update_scope == UpdateScope.REPOSITORY
                    or (
                            update_scope == UpdateScope.FILE
                            and mutation.path in files
                    )
            )

            if not applies:
                continue

            if invalidation == Invalidation.DISCARD:
                return Invalidation.DISCARD

            result = Invalidation.REFRESH

        return result

    def add_event(self, event: ToolEvent) -> None:
        if event.is_fail():
            self.short_memory.learnings.append(
                Learning(
                    tool=event.call.name,
                    args=event.call.args,
                    message=event.output.output.message,
                    metadata=event.output.learning_metadata
                )
            )
            return

        if not event.output.mutations:
            self.short_memory.events.append(event)
            return

        mutations = event.output.mutations
        updated_events: list[ToolEvent] = []

        for saved_event in self.short_memory.events:
            invalidation = self._get_invalidation(
                update_when=saved_event.update_when,
                update_scope=saved_event.update_scope,
                mutations=mutations,
                files=saved_event.output.files,
            )

            if invalidation is None:
                updated_events.append(saved_event)

            elif invalidation == Invalidation.REFRESH:
                saved_event.output = self.tools_api.execute_call(
                    call=saved_event.call
                ).output

                if not saved_event.is_fail():
                    updated_events.append(saved_event)


        self.short_memory.events = updated_events

        assert event.call.mutation_summary is not None

        self.short_memory.pending_mutations.append(
            MutationSummary(
                name=event.call.name,
                summary=event.call.mutation_summary,
            )
        )

    def finish_session(
            self,
            loop_completed: bool = False,
            output: str | None = None,
    ) -> None:
        if self.current_query is None:
            raise RuntimeError("No active session")

        current_query = self.current_query
        short_memory = self.short_memory

        self.short_memory = ShortMemory()
        self.current_query = None

        query_record = QueryRecord(
            query=current_query,
            mutation_summaries=list(
                short_memory.pending_mutations
            ),
            final_response=output,
            loop_completed=loop_completed,
        )

        persistent_learnings = [
            learning.to_persistent()
            for learning in short_memory.learnings
            if (
                learning.metadata is not None
                and learning.metadata.persistent
            )
        ]

        for learning in persistent_learnings:
            self.long_memory.add_learning(learning)
        self.long_memory.query_records.append(query_record)

    def start_session(self, query: str) -> None:
        if self.current_query is not None:
            raise RuntimeError("A session is already active")

        self.short_memory = ShortMemory()
        self.current_query = query

    @staticmethod
    def _format_context_elements[T: ContextElement](
            tag: str,
            elements: list[T],
    ) -> str:
        content = json.dumps(
            [element.to_context() for element in elements],
            ensure_ascii=False,
        )

        return (
            f"<{tag}>\n"
            f"{content}\n"
            f"</{tag}>"
        )

    def format_context(self) -> str:
        sections: list[str] = []

        if self.long_memory.query_records:
            sections.append(
                self._format_context_elements(
                    tag="query_records",
                    elements=self.long_memory.query_records,
                )
            )

        if self.long_memory.learnings:
            sections.append(
                self._format_context_elements(
                    tag="persistent_learnings",
                    elements=self.long_memory.learnings,
                )
            )

        if self.short_memory.pending_mutations:
            sections.append(
                self._format_context_elements(
                    tag="current_mutations",
                    elements=self.short_memory.pending_mutations,
                )
            )

        if self.short_memory.learnings:
            sections.append(
                self._format_context_elements(
                    tag="current_learnings",
                    elements=self.short_memory.learnings,
                )
            )

        if self.short_memory.events:
            sections.append(
                self._format_context_elements(
                    tag="current_tool_context",
                    elements=self.short_memory.events,
                )
            )

        if self.current_query is not None:
            sections.append(
                "<current_query>\n"
                f"{self.current_query}\n"
                "</current_query>"
            )

        return "\n\n".join(sections)
