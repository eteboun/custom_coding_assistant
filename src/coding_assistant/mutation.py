"""Repository changes shared by backends, tools, and memory."""

from dataclasses import dataclass
from enum import StrEnum

from .interfaces import LogElement


class Operation(StrEnum):
    UPDATE = "update"
    DELETE = "delete"
    ADD = "add"


@dataclass(frozen=True)
class Mutation(LogElement):
    path: str
    type: Operation

    def to_log(self) -> dict:
        return {"path": self.path, "type": self.type.value}
