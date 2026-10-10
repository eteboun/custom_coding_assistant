from __future__ import annotations

from pydantic import BaseModel, model_validator
from dataclasses import dataclass, asdict
from typing import Literal, Self
from decimal import Decimal

from .pricing import calculate_cost_usd
from ..interfaces import LogElement

ProviderId = Literal[
    "openai"
]

ReasoningLevel = Literal[
                    "none", "minimal", "low", "medium", "high", "xhigh", "max"
               ]

class Reasoning(BaseModel):
    levels: list[ReasoningLevel]
    default: ReasoningLevel | None

    @model_validator(mode="after")
    def validate_reasoning(self) -> Self:
        if self.default is not None and self.default not in self.levels:
            raise ValueError(
                f"Default reasoning '{self.default}' is not in reasoning levels"
            )

        return self


class ModelPricing(BaseModel):
    input: float
    output: float

    cached_input: float | None = None


class AboveThresholdPricing(BaseModel):
    input: float
    output: float


class ModelPricingRules(BaseModel):
    long_context_threshold: int | None = None

    above_threshold_input_multiplier: float | None = None
    above_threshold_output_multiplier: float | None = None

    above_threshold: AboveThresholdPricing | None = None


class ModelData(BaseModel):
    id: str
    provider: ProviderId

    context_window: int
    max_output_tokens: int

    reasoning: Reasoning

    pricing: ModelPricing
    pricing_rules: ModelPricingRules | None = None

class ModelsData(BaseModel):
    currency: Literal["USD"]
    pricing_unit: Literal["per_1m_tokens"]

    models: dict[str, ModelData]

@dataclass
class TokenUsage(LogElement):
    input_tokens: int = 0
    output_tokens: int = 0

    reasoning_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None

    total_tokens: int = 0
    total_cost: Decimal = Decimal("0.0")

    def set_cost(self, model_data: ModelData):
        self.total_cost = calculate_cost_usd(
            self,
            model_data
        )

    def to_log(self) -> dict:
        return {**asdict(self), 'total_cost': float(self.total_cost)}

    @staticmethod
    def _add_optional(total: int | None, value: int | None) -> int | None:
        if value is None:
            return total

        return (total or 0) + value

    def add(self, other: TokenUsage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.total_tokens += other.total_tokens
        self.total_cost += other.total_cost

        self.reasoning_tokens = self._add_optional(
            total=self.reasoning_tokens,
            value=other.reasoning_tokens
        )
        self.cached_input_tokens = self._add_optional(
            total=self.cached_input_tokens,
            value=other.cached_input_tokens
        )
        self.cache_write_tokens = self._add_optional(
            total=self.cache_write_tokens,
            value=other.cache_write_tokens
        )
