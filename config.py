from pathlib import Path
from pydantic import BaseModel
from typing import Self, Literal
import json

BASE_DIR = Path(__file__).resolve().parent

instructions = (
    BASE_DIR / "instructions.txt"
).read_text(encoding="utf-8")

class Config(BaseModel):

    model_name: str
    reasoning: Literal[
                   "none", "minimal", "low", "medium", "high", "xhigh", "max"
               ] | None = None

    max_iters: int

    repo_path: Path
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

        obj.repo_path = (json_path.parent / obj.repo_path).resolve()
        obj.log_path = (json_path.parent / obj.log_path).resolve()

        if not obj.repo_path.exists():
            raise FileNotFoundError(
                f"repo path {obj.repo_path} does not exist"
            )

        if not obj.repo_path.is_dir():
            raise NotADirectoryError(
                f"repo path {obj.repo_path} is not a directory"
            )

        obj.log_path.mkdir(parents=False, exist_ok=True)

        return obj
