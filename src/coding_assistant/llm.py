from pathlib import Path

from .ai.config import Config
from .ai.schemas import models_data

from .providers.base import BaseLLM
from .providers.google import GeminiLLM
from .providers.openai import OpenAILLM
from .providers.anthropic import AnthropicLLM

def create_llm(
        instructions: str,
        repo_path: Path,
        config: Config
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
                config=config
            )

        case "google":
            return GeminiLLM(
                instructions=instructions,
                repo_path=repo_path,
                config=config
            )

        case "anthropic":
            return AnthropicLLM(
                instructions=instructions,
                repo_path=repo_path,
                config=config
            )

        case _:
            raise ValueError(
                f"Unknown provider {model_data.provider}"
            )