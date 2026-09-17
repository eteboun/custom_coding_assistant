from pathlib import Path
from typing import assert_never

from .base import BaseLLM
from .google import GeminiLLM
from .openai import OpenAILLM
from .anthropic import AnthropicLLM

from ..config import Config

from ..models.models import models_data
from ..memory.memory import LongMemory

def create_llm(
        instructions: str,
        repo_path: Path,
        config: Config,
        long_memory: LongMemory | None = None
) -> BaseLLM:
    model_data = models_data.models.get(config.model_name)

    if model_data is None:
        raise ValueError(
            f"Model {config.model_name} not found."
        )

    match model_data.provider:
        case "openai":
            return OpenAILLM(
                instructions=instructions,
                repo_path=repo_path,
                config=config,
                long_memory=long_memory
            )

        case "google":
            return GeminiLLM(
                instructions=instructions,
                repo_path=repo_path,
                config=config,
                long_memory=long_memory
            )

        case "anthropic":
            return AnthropicLLM(
                instructions=instructions,
                repo_path=repo_path,
                config=config,
                long_memory=long_memory
            )

        case _:
            assert_never(model_data.provider)
