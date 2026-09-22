from typing import assert_never

from .base import BaseLLM
from .openai import OpenAILLM

from coding_assistant.assistant.config import Config

from ..models.models import models_data

def create_llm(
        instructions: str,
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
                config=config
            )

        case _:
            assert_never(model_data.provider)
