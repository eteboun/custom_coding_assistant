"""Formatting of memory elements for model input."""

import json

from .interfaces import ContextElement


def format_context_structure[T: ContextElement](
    tag: str,
    structure: str | list[T],
) -> str:
    content = (
        structure if isinstance(structure, str)
        else json.dumps([element.to_context() for element in structure], ensure_ascii=False)
    )
    return f'<{tag}>\n{content}\n</{tag}>'
