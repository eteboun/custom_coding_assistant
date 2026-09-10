from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import json

from ..utils import Serializable
from ..tools.utils import OutputProtocol
from .schemas import TokenUsage

@dataclass
class ToolCallLog(Serializable):
    name: str
    args: dict
    output: OutputProtocol | None = None

    def serialize(self) -> dict:
        return {
            "name": self.name,
            "args": self.args,
            **(
                {
                    "output": self.output.serialize()
                } if self.output is not None
                else {}
            )
        }

@dataclass
class LLMCallLog(Serializable):
    usage: TokenUsage

    def serialize(self) -> dict:
        return self.usage.serialize()

@dataclass
class LLMToolCallLog(LLMCallLog):
    tool_calls: list[ToolCallLog]

    def serialize(self) -> dict:
        return {
            "usage": super().serialize(),
            "tool_calls": [
                call.serialize()
                for call in self.tool_calls
            ],
        }

@dataclass
class LLMFinalCallLog(LLMCallLog):
    response: str

    def serialize(self) -> dict:
        return {
            "usage": super().serialize(),
            "response": self.response
        }

@dataclass
class QueryLog(Serializable):
    query: str
    llm_calls: list[LLMCallLog] = field(default_factory=list)

    def add_llm_call(self, llm_call: LLMCallLog) -> None:
        self.llm_calls.append(llm_call)

    @staticmethod
    def _add_optional(total: int | None, value: int | None) -> int | None:
        if value is None:
            return total

        return (total or 0) + value

    def serialize(self) -> dict:
        total_input_tokens = 0
        total_output_tokens = 0
        total_tokens = 0

        total_reasoning_tokens: int | None = None
        total_cached_input_tokens: int | None = None
        total_cached_write_tokens: int | None = None

        for call in self.llm_calls:
            total_input_tokens += call.usage.input_tokens
            total_output_tokens += call.usage.output_tokens
            total_tokens += call.usage.total_tokens

            total_reasoning_tokens = self._add_optional(
                total=total_reasoning_tokens,
                value=call.usage.reasoning_tokens
            )
            total_cached_input_tokens = self._add_optional(
                total=total_cached_input_tokens,
                value=call.usage.cached_input_tokens
            )
            total_cached_write_tokens = self._add_optional(
                total=total_cached_write_tokens,
                value=call.usage.cached_write_tokens
            )

        usage = TokenUsage(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            reasoning_tokens=total_reasoning_tokens,
            cached_input_tokens=total_cached_input_tokens,
            cache_write_tokens=total_cached_write_tokens,
            total_tokens=total_tokens,
        )

        return {
            "query": self.query,
            "llm_calls": [
                call.serialize()
                for call in self.llm_calls
            ],
            "usage": usage.serialize()
        }

@dataclass
class Logger(Serializable):
    log_path: Path
    query_logs: list[QueryLog] = field(default_factory=list)

    def serialize(self) -> list:
        return [
            query_log.serialize()
            for query_log in self.query_logs
        ]

    def add_query_log(self, query_log: QueryLog) -> None:
        self.query_logs.append(query_log)

    def log(self) -> None:
        self.log_path.mkdir(parents=True, exist_ok=True)

        name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        data = self.serialize()

        with open(self.log_path / f"{name}.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
