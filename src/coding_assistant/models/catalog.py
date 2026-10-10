from .schema import ModelsData
from ..resources import models_json

def _load_models() -> ModelsData:
    return ModelsData.model_validate_json(models_json.read_text(encoding='utf-8'))

models_data = _load_models()
