from dataclasses import dataclass, field

from ..tools.context import ToolEvent
from ..utils import LogElement, FormattableContext, format_context_structure

from .schema import MemoryElement, QueryElement, ToolEventElement, OutputTextElement, QueryRecord

@dataclass
class Memory(LogElement, FormattableContext):
    """Queries, complete tool events, and output texts in insertion order."""

    elements: list[MemoryElement] = field(default_factory=list, init=False)
    query_records: list[QueryRecord] = field(default_factory=list, init=False)
    context_size: int = field(default=0, init=False)
    context_size_is_estimate: bool = field(default=False, init=False)

    def add_query_record(self, record: QueryRecord) -> None:
        self.query_records.append(record)

    def compress(self, active_elements: list[MemoryElement] | None = None) -> None:
        """Replace earlier work with records and retain the active task's elements."""
        self.elements = [*self.query_records, *(active_elements or [])]

    def add_element(self, element: MemoryElement) -> None:
        if not isinstance(element, MemoryElement):
            raise TypeError('Expected a MemoryElement')
        self.elements.append(element)

    def add_query(self, query: str) -> None:
        self.add_element(QueryElement(query))

    def add_event(self, event: ToolEvent) -> None:
        self.add_element(ToolEventElement(event))

    def add_output_text(self, text: str) -> None:
        self.add_element(OutputTextElement(text))

    def to_log(self) -> dict:
        return {'elements': [element.to_log() for element in self.elements]}

    def format_context(self) -> str:
        if not self.elements:
            return ''
        return format_context_structure(tag='memory', structure=self.elements)
