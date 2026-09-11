from __future__ import annotations

from pydantic import BaseModel
from typing import Literal, Any
from pathlib import Path
from dataclasses import dataclass, field

from ..utils import Serializable
from .config import models_json, workflows_dir

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

@dataclass
class Workflow:
    path: Path
    name: str

    @property
    def content(self):
        return (self.path / f"{self.name}.md").read_text()

    @property
    def summary(self):
        return (self.path / "summary.txt").read_text()

class WorkflowSelection(BaseModel):
    workflow: Literal[
        "documentation",
        "build",
        "bug_fix",
        "new_feature",
        "investigation"
    ]

@dataclass
class Workflows:
    instructions: str

    map: dict[str, Workflow] = field(
        default_factory=lambda: {
            f.name: Workflow(
                name=f.name,
                path=f.resolve(),
            )
            for f in workflows_dir.iterdir()
        }
    )

    def __post_init__(self):
        self.instructions = self.instructions.format(
            available_workflows="\n".join(
                f"- {workflow.name}: {workflow.summary}"
                for workflow in self.map.values()
            )
        )

    def from_selection(self, selection: WorkflowSelection) -> Workflow:
        return self.map[selection.workflow]

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
    with open(models_json) as f:
        return ModelsData.model_validate_json(
            f.read()
        )

class TokenUsage(BaseModel, Serializable):
    input_tokens: int = 0
    output_tokens: int = 0

    reasoning_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_tokens: int | None = None

    total_tokens: int = 0

    def serialize(self) -> Any:
        return self.model_dump()

    @staticmethod
    def _add_optional(total: int | None, value: int | None) -> int | None:
        if value is None:
            return total

        return (total or 0) + value

    def add(self, other: TokenUsage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.total_tokens += other.total_tokens

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

models_data = _load_models()

models_by_provider: dict[ProviderId, list[ModelData]] = {}
for model_data in models_data.models.values():
    models_by_provider.setdefault(
        model_data.provider, []
    ).append(model_data)