from dataclasses import dataclass, field
from tools import FunctionToolNames
from datetime import datetime
from config import log_path
import json

@dataclass
class FunctionToolCallLog:
    name: FunctionToolNames
    args: dict

    def serialize(self) -> dict:
        return {
            "name": self.name.value,
            "args": self.args,
        }

@dataclass
class LLMCallLog:
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int

    def serialize(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens
        }

@dataclass
class LLMToolCallLog(LLMCallLog):
    tool_calls: list[FunctionToolCallLog]

    def serialize(self) -> dict:
        return {
            **super().serialize(),
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
            **super().serialize(),
            "response": self.response,
        }

@dataclass
class SessionLogger:
    query: str
    llm_calls: list[LLMCallLog] = field(default_factory=list)

    total_llm_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_reasoning_tokens: int = 0
    total_tokens: int = 0

    def add_llm_call(self, llm_call: LLMCallLog) -> None:
        self.llm_calls.append(llm_call)
        self.total_llm_calls += 1
        self.total_input_tokens += llm_call.input_tokens
        self.total_output_tokens += llm_call.output_tokens
        self.total_reasoning_tokens += llm_call.reasoning_tokens
        self.total_tokens += (llm_call.input_tokens
                              + llm_call.output_tokens
                              + llm_call.reasoning_tokens)

    def serialize(self) -> dict:
        return {
            "query": self.query,
            "llm_calls": [
                call.serialize()
                for call in self.llm_calls
            ],
            "total_llm_calls": self.total_llm_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_reasoning_tokens": self.total_reasoning_tokens,
            "total_tokens": self.total_tokens
        }

    def log(self) -> None:
        log_path.mkdir(parents=True, exist_ok=True)

        name = datetime.now().strftime("%Y-%m-%d_%H-%M-%S-%f")
        data = self.serialize()

        with open(log_path / f"{name}.json", "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)