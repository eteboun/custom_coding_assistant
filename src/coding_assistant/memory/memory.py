from dataclasses import dataclass, field
from abc import abstractmethod

from ..tools.api import ToolsAPI
from ..tools.context import ToolEvent, UpdateScope, Operation, Mutation, Invalidation
from ..utils import LogElement, FormattableContext, format_context_structure

from .schema import (ShortMemory, LongMemory, IntermediateMemory,
                     Learning, MutationSummary, QueryRecord)

@dataclass
class Memory(LogElement, FormattableContext):
    long_memory: LongMemory = field(
        default_factory=LongMemory,
        init=False
    )
    current_query: str | None = field(default=None, init=False)

    @abstractmethod
    def start_query(self, query: str) -> None:
        ...

    @abstractmethod
    def finish_query(
            self,
            loop_completed: bool = False,
            output: str | None = None
    ) -> None:
        ...

    @abstractmethod
    def add_event(self, event: ToolEvent) -> None:
        ...


@dataclass
class ActiveMemory(Memory):
    tools_api: ToolsAPI
    short_memory: ShortMemory = field(
        default_factory=ShortMemory,
        init=False
    )

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

    def to_log(self) -> dict:
        return {
            "short_memory": self.short_memory.to_log(),
            "long_memory": self.long_memory.to_log(),
            "context": self.format_context()
        }

    def add_event(self, event: ToolEvent) -> None:
        if event.is_fail():
            self.short_memory.learnings.append(
                Learning(
                    tool=event.call.name,
                    args=event.call.args,
                    message=event.output.message,
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

    def finish_query(
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

    def start_query(self, query: str) -> None:
        if self.current_query is not None:
            raise RuntimeError("A session is already active")

        self.short_memory = ShortMemory()
        self.current_query = query

    def format_context(self) -> str:
        sections = [
            context
            for context in (
                self.long_memory.format_context(),
                self.short_memory.format_context(),
            )
            if context
        ]

        if self.current_query is not None:
            sections.append(
                format_context_structure(
                    tag="current_query",
                    structure=self.current_query
                )
            )

        return "\n\n".join(sections)

@dataclass
class PersistentMemory(Memory):
    intermediate_memory: IntermediateMemory = field(
        default_factory=IntermediateMemory,
        init=False
    )

    def add_event(self, event: ToolEvent) -> None:
        if (
                event.is_fail()
                and event.output.learning_metadata.persistent
        ):
            self.intermediate_memory.learnings.append(
                Learning(
                    tool=event.call.name,
                    args=event.call.args,
                    message=event.output.message,
                    metadata=event.output.learning_metadata
                ).to_persistent()
            )
            return

        if not event.output.mutations:
            return

        self.intermediate_memory.mutations.append(
            MutationSummary(
                name=event.call.name,
                summary=event.call.mutation_summary
            )
        )

    def to_log(self) -> dict:
        return {
            "long_memory": self.long_memory.to_log(),
            "intermediate_memory": self.intermediate_memory.to_log(),
            "context": self.format_context()
        }

    def format_context(self) -> str:
        long_memory_context = self.long_memory.format_context()

        sections: list[str] = (
            [long_memory_context]
            if long_memory_context else
            []
        )

        if self.current_query is not None:
            sections.append(
                format_context_structure(
                    tag="current_query",
                    structure=self.current_query
                )
            )

        return "\n\n".join(sections)

    def finish_query(
            self,
            loop_completed: bool = False,
            output: str | None = None,
    ) -> None:
        if self.current_query is None:
            raise RuntimeError("No active session")

        current_query = self.current_query
        intermediate_memory = self.intermediate_memory

        self.intermediate_memory = IntermediateMemory()
        self.current_query = None

        query_record = QueryRecord(
            query=current_query,
            mutation_summaries=list(
                intermediate_memory.mutations
            ),
            final_response=output,
            loop_completed=loop_completed
        )

        for learning in intermediate_memory.learnings:
            self.long_memory.add_learning(learning)
        self.long_memory.query_records.append(query_record)

    def start_query(self, query: str) -> None:
        if self.current_query is not None:
            raise RuntimeError("A session is already active")

        self.intermediate_memory = IntermediateMemory()
        self.current_query = query
