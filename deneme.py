
from typing import Optional

def ratio(a: int, b: int) -> float:
    if b == 0:
        raise ValueError("b must not be zero")
    return a / b