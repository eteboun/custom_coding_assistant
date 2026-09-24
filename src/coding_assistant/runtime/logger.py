from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import json

from ..utils import LogElement, LogError
from ..models.schema import TokenUsage


@dataclass
class LLMCallLog(LogElement):
    usage: TokenUsage
    initial_memory: dict[str, Any] | None = field(
        default=None,
        init=False
    )

    def to_log(self) -> dict:
        return {
            "initial_memory": self.initial_memory,
            "usage": self.usage.to_log()
        }


@dataclass
class LLMToolEventLog(LLMCallLog):
    events: list[dict] = field(default_factory=list)
    final_memory: dict[str, Any] | None = field(
        default=None,
        init=False
    )

    def to_log(self) -> dict:
        return {
            **super().to_log(),
            "events": self.events,
            "final_memory": self.final_memory
        }


@dataclass
class LLMFinalCallLog(LLMCallLog):
    response: str

    def to_log(self) -> dict:
        return {
            **super().to_log(),
            "response": self.response
        }

@dataclass
class QueryLog(LogElement):
    query: str
    errors: list[Exception] = field(
        default_factory=list
    )
    session_final_memory: dict[str, Any] | None = field(
        default=None,
        init=False
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
            "session_final_memory": self.session_final_memory,
            "llm_calls": [
                llm_call.to_log()
                for llm_call in self.llm_calls
            ],
            "total_usage": self.total_usage().to_log(),
            "errors": [
                str(e)
                for e in self.errors
            ],
        }

@dataclass
class Logger(LogElement):
    log_path: Path
    query_logs: list[QueryLog] = field(default_factory=list)

    def to_log(self) -> dict[str, Any]:
        return {
                "queries": [
                    query_log.to_log()
                    for query_log in self.query_logs
                ],
                "total_usage": self.total_usage().to_log()
            }

    def total_usage(self) -> TokenUsage:
        usage = TokenUsage()

        for query_log in self.query_logs:
            usage.add(query_log.total_usage())

        return usage

    def add_query_log(self, query_log: QueryLog) -> None:
        self.query_logs.append(query_log)

    def log(self) -> str:
        if not self.query_logs:
            raise LogError(
                "Nothing to log"
            )

        self.log_path.mkdir(parents=True, exist_ok=True)

        name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")

        with open(self.log_path / f"{name}.json", "w", encoding="utf-8") as f:
            json.dump(self.to_log(), f, ensure_ascii=False, indent=4)

        return name
