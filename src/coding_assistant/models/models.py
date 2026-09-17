from .schema import ModelsData, ModelData, ProviderId
from ..config import models_json

def _load_models() -> ModelsData:
    with open(models_json) as f:
        return ModelsData.model_validate_json(
            f.read()
        )

models_data = _load_models()

models_by_provider: dict[ProviderId, list[ModelData]] = {}
for model_data in models_data.models.values():
    models_by_provider.setdefault(
        model_data.provider, []
    ).append(model_data)