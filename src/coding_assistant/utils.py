from abc import abstractmethod, ABC
from typing import Any
from pathlib import Path
import json

_BASE_DIR = Path(__file__).resolve().parent

instructions = (
    _BASE_DIR / "instructions.md"
).read_text()

config_file = _BASE_DIR / "assistant.json"
models_json = _BASE_DIR / "models.json"

class LogElement(ABC):
    @abstractmethod
    def to_log(self) -> Any:
        ...

class ContextElement(ABC):
    @abstractmethod
    def to_context(self) -> dict:
        ...

def format_context_structure[T: ContextElement](
        tag: str,
        structure: str | list[T],
) -> str:
    if isinstance(structure, str):
        content = structure

    else:
        content = json.dumps(
            [element.to_context() for element in structure],
            ensure_ascii=False,
        )

    return (
        f"<{tag}>\n"
        f"{content}\n"
        f"</{tag}>"
    )

class FormattableContext(ABC):
    @abstractmethod
    def format_context(self) -> str:
        ...

class RecoverableError(Exception):
    pass

class CommandError(RecoverableError):
    pass

class MaxIterationsError(RecoverableError):
    pass

class LogError(RecoverableError):
    pass
