"""Secondary module for multi-file Python extraction test."""

from typing import Protocol


class Processor(Protocol):
    """Protocol defining a processor interface."""

    def process(self, data: bytes) -> bytes: ...


def run_pipeline(steps: list) -> None:
    """Execute a processing pipeline."""
    pass


BATCH_SIZE = 100
