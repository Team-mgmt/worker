from .base import BaseLogger


class ConsoleLogger(BaseLogger):
    """Logger that outputs logs to the console."""

    async def info(self, message: str) -> None:
        print(f"[INFO] {message}")

    async def warn(self, message: str) -> None:
        print(f"[WARN] {message}")

    async def error(self, message: str) -> None:
        print(f"[ERROR] {message}")
