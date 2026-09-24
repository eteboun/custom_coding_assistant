from .schema import ModelsData
from ..utils import models_json

def _load_models() -> ModelsData:
    with open(models_json) as f:
        return ModelsData.model_validate_json(
            f.read()
        )

models_data = _load_models()
