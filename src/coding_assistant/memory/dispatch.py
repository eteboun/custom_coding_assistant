from typing import assert_never

from ..tools.api import ToolsAPI
from .memory import ActiveMemory, PersistentMemory, Memory
from .architectures import (ArchitectureName, PrevIdArchitecture, Architecture,
                            PersistentMemoryArchitecture, ActiveMemoryArchitecture)

def create_architecture(
        name: ArchitectureName,
        api: ToolsAPI
) -> tuple[Architecture, Memory | None]:
    match name:
        case "prev_id":
            return PrevIdArchitecture(), None

        case "persistent_memory":
            return PersistentMemoryArchitecture(), PersistentMemory()

        case "active_memory":
            return ActiveMemoryArchitecture(), ActiveMemory(api)

        case _:
            raise assert_never(name)
