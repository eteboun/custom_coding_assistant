from .schema import ModelData, ReasoningLevel
from .models import models_data

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
