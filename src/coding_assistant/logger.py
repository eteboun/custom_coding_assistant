from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import json

from .utils import LogElement, LogError
from .models.schema import TokenUsage


@dataclass
class LLMCallLog(LogElement):
    usage: TokenUsage

    def to_log(self) -> dict:
        return self.usage.to_log()

@dataclass
class LLMToolEventLog(LLMCallLog):
    memory: dict[str, Any]
    events: list[dict]

    def to_log(self) -> dict:
        return {
            "usage": super().to_log(),
            "events": self.events,
            "memory": self.memory
        }

@dataclass
class LLMFinalCallLog(LLMCallLog):
    response: str

    def to_log(self) -> dict:
        return {
            "usage": super().to_log(),
            "response": self.response
        }

@dataclass
class QueryLog(LogElement):
    query: str
    initial_memory: dict[str, Any]
    final_memory: dict[str, Any] = field(
        init=False,
        default_factory=dict,
    )
    llm_calls: list[LLMCallLog] = field(
        init=False,
        default_factory=list,
    )

    def add_llm_call(self, llm_call: LLMCallLog) -> None:
        self.llm_calls.append(llm_call)

    def total_usage(self) -> TokenUsage:
        usage = TokenUsage()

        for llm_call in self.llm_calls:
            usage.add(llm_call.usage)

        return usage

    def to_log(self) -> dict:
        return {
            "query": self.query,
            "initial_memory": self.initial_memory,
            "final_memory": self.final_memory,
            "llm_calls": [
                llm_call.to_log()
                for llm_call in self.llm_calls
            ],
            "total_usage": self.total_usage().to_log()
        }

@dataclass
class Logger(LogElement):
    log_path: Path
    query_logs: list[QueryLog] = field(default_factory=list)

    def to_log(self) -> list[dict[str, Any]]:
        return [
            query_log.to_log()
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
        if not self.query_logs:
            raise LogError(
                "Nothing to log"
            )

        self.log_path.mkdir(parents=True, exist_ok=True)

        name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")

        with open(self.log_path / f"{name}.json", "w", encoding="utf-8") as f:
            json.dump(self.to_log(), f, ensure_ascii=False, indent=4)
