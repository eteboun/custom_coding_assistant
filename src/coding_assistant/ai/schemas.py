from __future__ import annotations

from pydantic import BaseModel
from typing import Literal, Any
from pathlib import Path

from ..utils import Serializable

ProviderId = Literal[
    "openai",
    "anthropic",
    "google",
]

ReasoningLevel = Literal[
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
]

_BASE_DIR = Path(__file__).resolve().parent / "llm_data"
_models_json = _BASE_DIR / "models.json"

class ModelPricing(BaseModel):
    input: float
    output: float

    cached_input: float | None = None

    cache_write_5m: float | None = None
    cache_write_1h: float | None = None


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

    reasoning_levels: list[ReasoningLevel] | None = None

    pricing: ModelPricing
    pricing_rules: ModelPricingRules | None = None


class ModelsData(BaseModel):
    currency: Literal["USD"]
    pricing_unit: Literal["per_1m_tokens"]

    models: dict[str, ModelData]

def _load_models() -> ModelsData:
    with open(_models_json) as f:
        return ModelsData.model_validate_json(
            f.read()
        )

models_data = _load_models()

class TokenUsage(BaseModel, Serializable):
    input_tokens: int
    output_tokens: int

    reasoning_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None

    total_tokens: int

    def serialize(self) -> Any:
        return self.model_dump()
