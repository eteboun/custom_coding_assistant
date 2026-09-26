"""Successful results returned by repository backends."""

from dataclasses import dataclass
from typing import Any

from ..mutation import Mutation


@dataclass(frozen=True)
class OperationResult:
    content: Any
    files: tuple[str, ...] = ()
    mutations: tuple[Mutation, ...] = ()
