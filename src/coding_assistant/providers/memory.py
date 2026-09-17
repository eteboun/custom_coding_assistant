
from dataclasses import dataclass, field

from ..tools.schemas import (ToolCall, ToolOutput, UpdateScope,
                             Metadata, Mutation, Invalidation)
from ..utils import Serializable
from ..tools.content import Tools

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

class ToolEvent:
    call: ToolCall
    output: ToolOutput

    def is_fail(self) -> bool:
        return self.output.output.is_fail()

@dataclass(frozen=True)
class Learning:
    tool: str
    args: dict
    message: str


@dataclass
class LongMemory:
    query_records: list[QueryRecord] = field(default_factory=list)


@dataclass
class ShortMemory:
    tools: Tools
    events: list[ToolEvent] = field(default_factory=list)
    learnings: list[Learning] = field(default_factory=list)
    pending_mutations: list[MutationSummary] = field(default_factory=list)

    @staticmethod
    def _get_invalidation(
            metadata: Metadata,
            mutations: tuple[Mutation, ...],
            files: tuple[str, ...],
    ) -> Invalidation | None:
        result: Invalidation | None = None

        for mutation in mutations:
            invalidation = metadata.update_when.get(mutation.type)

            if invalidation is None:
                continue

            applies = (
                    metadata.update_scope == UpdateScope.REPOSITORY
                    or (
                            metadata.update_scope == UpdateScope.FILE
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
            self.learnings.append(
                Learning(
                    tool=event.call.name,
                    args=event.call.args,
                    message=event.output.output.message,
                )
            )
            return

        if not event.output.mutations:
            self.events.append(event)
            return

        mutations = event.output.mutations
        updated_events: list[ToolEvent] = []

        for saved_event in self.events:
            metadata = self.tools.data_mapping[
                saved_event.call.name
            ].metadata

            invalidation = self._get_invalidation(
                metadata=metadata,
                mutations=mutations,
                files=saved_event.output.files,
            )

            if invalidation is None:
                updated_events.append(saved_event)

            elif invalidation == Invalidation.REFRESH:
                saved_event.output = self.tools.execute_call(
                    call=saved_event.call
                )

                if not saved_event.is_fail():
                    updated_events.append(saved_event)


        self.events = updated_events

        assert event.call.mutation_summary is not None

        self.pending_mutations.append(
            MutationSummary(
                name=event.call.name,
                summary=event.call.mutation_summary,
            )
        )

@dataclass
class ActiveMemory:
    short_memory: ShortMemory
    long_memory: LongMemory

