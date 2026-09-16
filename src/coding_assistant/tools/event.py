from dataclasses import dataclass
from typing import Literal

from .schemas import Operation
from ..utils import OutputProtocol

UpdateScope = Literal["repository", "file"]
MutationType = Operation

@dataclass(frozen=True)
class Mutation:
    path: str
    type: MutationType


@dataclass(frozen=True)
class ToolOutput:
    output: OutputProtocol
    files: tuple[str, ...] = ()
    mutations: tuple[Mutation, ...] = ()


@dataclass
class ToolEvent:
    name: str
    args: dict
    id: str

    update_scope: UpdateScope | None = None
    update_when: tuple[MutationType, ...] = ()

    output: ToolOutput | None = None
    mutation_summary: str | None = None

    def __post_init__(self):
        self.mutation_summary = self.args.pop("change_summary", None)



