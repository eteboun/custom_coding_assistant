from abc import abstractmethod, ABC
from typing import Any

class Serializable(ABC):

    @abstractmethod
    def serialize(self) -> Any:
        ...

