from .schema import ProviderId, ModelData, ReasoningLevel
from .models import models_data

def resolve_model(
        model_name: str,
        provider: ProviderId
) -> ModelData:
    model_data = models_data.models.get(
        model_name
    )

    if model_data is None:
        raise ValueError(
            f"Model {model_name} is not recognized"
        )

    if model_data.provider != provider:
        raise ValueError(
            f"Model {model_name} does not belong to {provider}"
        )

    return model_data


def resolve_reasoning(
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
