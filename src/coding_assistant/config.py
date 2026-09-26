from pathlib import Path
from pydantic import BaseModel, Field, model_validator
from typing import Self
import json

from coding_assistant.models.schema import ReasoningLevel
from coding_assistant.models.operations import resolve_model_config
from coding_assistant.memory.architectures import ArchitectureName

class Config(BaseModel):

    model_name: str
    reasoning: ReasoningLevel | None
    architecture: ArchitectureName

    max_iters: int = Field(ge=1)

    log_path: Path

    blocked_files: list[Path]
    blocked_dirs: list[Path]

    @model_validator(mode="after")
    def validate_model_reasoning(self) -> Self:
        resolve_model_config(
            model_name=self.model_name,
            reasoning=self.reasoning
        )
        return self

    @staticmethod
    def _validate_json_path(json_path: Path) -> None:
        if not json_path.is_file():
            raise ValueError(f"{json_path} is not a file")

        if json_path.suffix.lower() != ".json":
            raise ValueError(f"{json_path} is not a JSON file")

    @classmethod
    def from_json(cls, json_path: Path, repo_path: Path) -> Self:
        json_path = json_path.resolve()
        cls._validate_json_path(json_path)

        with open(json_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)

        obj = cls.model_validate(json_data)

        obj.log_path = (repo_path / obj.log_path).resolve()
        obj.log_path.mkdir(parents=False, exist_ok=True)

        return obj
