from pathlib import Path
from pydantic import BaseModel
from typing import Self, Literal, get_args
import json

_BASE_DIR = Path(__file__).resolve().parent

instructions = (
    _BASE_DIR / "instructions.md"
).read_text()

config_filename = "assistant.json"
_config_reasoning_levels = Literal[
                    "low", "medium", "high"
               ]

config_reasoning_levels = get_args(_config_reasoning_levels)

models_json = _BASE_DIR.parent / "llm_data" / "models.json"

class Config(BaseModel):

    model_name: str
    reasoning: _config_reasoning_levels | None = None

    max_iters: int

    log_path: Path

    blocked_files: list[str]
    blocked_dirs: list[str]

    @staticmethod
    def _validate_json_path(json_path: Path) -> None:
        if not json_path.is_file():
            raise FileNotFoundError(f"{json_path} is not a file")

        if json_path.suffix.lower() != ".json":
            raise ValueError(f"{json_path} is not a JSON file")

    @classmethod
    def from_json(cls, json_path: str) -> Self:
        json_path = Path(json_path).resolve()

        cls._validate_json_path(json_path)

        with open(json_path, "r", encoding="utf-8") as f:
            json_data = json.load(f)

        obj = cls.model_validate(json_data)

        obj.log_path = (json_path.parent / obj.log_path).resolve()
        obj.log_path.mkdir(parents=False, exist_ok=True)

        return obj
