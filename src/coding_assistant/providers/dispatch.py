from typing import assert_never

from .base import BaseLLM
from .openai import OpenAILLM

from ..models.schema import ModelData, ReasoningLevel

def create_llm(
        instructions: str,
        model_data: ModelData,
        reasoning: ReasoningLevel | None,
        max_iters: int,
) -> BaseLLM:
    match model_data.provider:
        case "openai":
            return OpenAILLM(
                instructions=instructions,
                reasoning=reasoning,
                max_iters=max_iters,
                model_data=model_data
            )

        case _:
            assert_never(model_data.provider)
