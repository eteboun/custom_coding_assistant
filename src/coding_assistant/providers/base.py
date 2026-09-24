from abc import ABC, abstractmethod

from ..models.schema import TokenUsage, ReasoningLevel, ModelData

from ..tools.context import ToolCall, ToolOutput
from ..tools.schema import ToolSchema

class BaseLLM[ClientT](ABC):
    def __init__(
        self,
        instructions: str,
        model_data: ModelData,
        reasoning: ReasoningLevel | None,
        max_iters: int,
        client: ClientT
        ) -> None:

        self.client = client
        self.instructions = instructions

        self.model_data = model_data
        self.reasoning = reasoning
        self.max_iters = max_iters

    @abstractmethod
    def usage(self, response) -> TokenUsage:
        ...

    @abstractmethod
    def output_text(self, response) -> str:
        ...

    @abstractmethod
    def tool_call_contract(self, response) -> list[ToolCall]:
        ...

    @abstractmethod
    def tool_output_contract(self, outputs: list[ToolOutput]):
        ...

    @abstractmethod
    def tool_schema_contract(self, tools: list[ToolSchema]):
        ...

    @abstractmethod
    def generate(
            self,
            input_: str | list[tuple[ToolCall, ToolOutput]],
            tools: list[ToolSchema],
            prev_id: str | None = None
            ):
        ...

    @abstractmethod
    def response_id(self, response) -> str:
        ...
