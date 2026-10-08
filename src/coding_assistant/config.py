from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator
from pathlib import Path
from typing import Self

from coding_assistant.models.schema import ReasoningLevel
from coding_assistant.models.operations import resolve_model_config

class Config(BaseModel):

    model_name: str
    reasoning: ReasoningLevel | None

    max_iters: int = Field(ge=1)

    log_path: Path

    blocked_files: list[Path]
    blocked_dirs: list[Path]

    @field_validator("log_path")
    @classmethod
    def resolve_log_path(cls, path: Path, info: ValidationInfo) -> Path:
        if isinstance(info.context, dict) and "repo_path" in info.context:
            return (Path(info.context["repo_path"]) / path).resolve()
        return path

    @model_validator(mode="after")
    def validate_model_reasoning(self) -> Self:
        resolve_model_config(
            model_name=self.model_name,
            reasoning=self.reasoning
        )
        return self
