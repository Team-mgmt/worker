from types import CodeType
from typing import Any

def compile_restricted(
    source: str,
    filename: str = ...,
    mode: str = ...,
    flags: int = ...,
    dont_inherit: bool = ...,
    policy: Any = ...,
) -> CodeType: ...

safe_builtins: dict[str, Any]
