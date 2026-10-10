"""Packaged defaults and agent instructions."""

from importlib.resources import files


_resource_root = files(__package__)
config_file = _resource_root.joinpath('assistant.json')
models_json = _resource_root.joinpath('models.json')
instructions = _resource_root.joinpath('instructions.md').read_text(encoding='utf-8')
