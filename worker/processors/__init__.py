from .base import BaseProcessor
from .v1 import ProcessorV1

PROCESSORS: dict[float, type[BaseProcessor]] = {
    1.0: ProcessorV1,
}


def get_processor(version: float) -> type[BaseProcessor]:
    if version not in PROCESSORS:
        raise ValueError(f"Unsupported processor version: {version}. Available versions: {list(PROCESSORS.keys())}")
    return PROCESSORS[version]


__all__ = ["BaseProcessor", "ProcessorV1", "get_processor", "PROCESSORS"]
