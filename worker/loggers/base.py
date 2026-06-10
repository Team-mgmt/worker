class BaseLogger:
    """Base logger class."""

    def __init__(self):
        if type(self) is BaseLogger:
            raise NotImplementedError("BaseLogger is an abstract class and cannot be instantiated directly.")

    async def info(self, message: str) -> None:
        raise NotImplementedError

    async def warn(self, message: str) -> None:
        raise NotImplementedError

    async def error(self, message: str) -> None:
        raise NotImplementedError
