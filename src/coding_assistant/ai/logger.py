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

    def total_usage(self) -> TokenUsage:
        usage = TokenUsage()

        for llm_call in self.llm_calls:
            usage.add(llm_call.usage)

        return usage

    def serialize(self) -> dict:

        return {
            "query": self.query,
            "llm_calls": [
                call.serialize()
                for call in self.llm_calls
            ],
            "usage": self.total_usage().serialize(),
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

    def total_usage(self) -> TokenUsage:
        usage = TokenUsage()

        for query_log in self.query_logs:
            usage.add(query_log.total_usage())

        return usage

    def add_query_log(self, query_log: QueryLog) -> None:
        self.query_logs.append(query_log)

    def log(self) -> None:
        self.log_path.mkdir(parents=True, exist_ok=True)

        name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        data = self.serialize()

        with open(self.log_path / f"{name}.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
