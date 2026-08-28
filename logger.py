from dataclasses import dataclass, field
from tools import FunctionToolNames

@dataclass
class FunctionToolCallLog:
    name: FunctionToolNames
    args: dict

@dataclass
class LLMCallLog:
    input_tokens: int
    output_tokens: int
    tool_calls: list[FunctionToolCallLog]

@dataclass
class SessionLogger:
    llm_calls: list[LLMCallLog] = field(default_factory=list)

    total_input_tokens: int = 0
    total_output_tokens: int = 0
