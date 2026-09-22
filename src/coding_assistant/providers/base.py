from abc import ABC, abstractmethod

from ..models.operations import resolve_reasoning, resolve_model
from ..models.schema import ProviderId, TokenUsage

from coding_assistant.assistant.config import Config

from ..tools.context import ToolCall
from ..tools.schema import ToolSchema

class BaseLLM[ClientT](ABC):
    def __init__(
        self,
        instructions: str,
        config: Config,
        client: ClientT,
        provider: ProviderId
        ):
        self.config = config
        self.client = client
        self.instructions = instructions

        self.model_data = resolve_model(
            model_name=config.model_name,
            provider=provider
        )

        self.reasoning = resolve_reasoning(
            model_data=self.model_data,
            reasoning=config.reasoning
        )

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
    def tool_schema_contract(self, tools: list[ToolSchema]):
        ...

    @abstractmethod
    def generate(
            self,
            context: str,
            tools: list[ToolSchema]
            ):
        ...
