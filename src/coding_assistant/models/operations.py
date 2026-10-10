from .schema import ModelData, ReasoningLevel
from .catalog import models_data
from typing import get_args


def resolve_model_switch(
    model_name: str,
    current_reasoning: ReasoningLevel | None,
) -> tuple[ModelData, ReasoningLevel | None]:
    model_data = _resolve_model(model_name)
    levels = model_data.reasoning.levels
    if not levels:
        return model_data, None
    if current_reasoning in levels:
        return model_data, current_reasoning
    if model_data.reasoning.default is not None:
        return model_data, model_data.reasoning.default
    order = get_args(ReasoningLevel)
    return model_data, min(levels, key=order.index)

def _resolve_model(
        model_name: str
) -> ModelData:
    model_data = models_data.models.get(
        model_name
    )

    if model_data is None:
        raise ValueError(
            f"Model {model_name} is not recognized"
        )

    return model_data


def _resolve_reasoning(
        model_data: ModelData,
        reasoning: ReasoningLevel | None
) -> ReasoningLevel | None:
    if model_data.reasoning.levels:
        if reasoning is None:
            reasoning = model_data.reasoning.default

            if reasoning is None:
                raise ValueError(
                    f"No default reasoning configured for model {model_data.id}"
                )

        elif reasoning not in model_data.reasoning.levels:
            raise ValueError(
                f"{model_data.id} does not support reasoning level {reasoning}"
            )

        return reasoning

    if reasoning is not None:
        raise ValueError(
            f"{model_data.id} does not support reasoning"
        )

    return None

def resolve_model_config(
    model_name: str,
    reasoning: str | None,
) -> tuple[ModelData, ReasoningLevel | None]:

    model_data = _resolve_model(model_name)

    effective_reasoning = _resolve_reasoning(
        model_data=model_data,
        reasoning=reasoning,
    )

    return model_data, effective_reasoning
