"""Sample module for testing Python tree-sitter extraction."""

import os
import sys
from pathlib import Path
from typing import Optional
from collections.abc import Callable


MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30
_private_var = "hidden"


class Config:
    """Holds application configuration."""

    def __init__(self, host: str, port: int = 8080):
        self.host = host
        self.port = port

    def start(self) -> None:
        print(f"Starting on {self.host}:{self.port}")

    def _validate(self) -> bool:
        return self.host != ""


class _InternalHelper:
    """Should not appear in exports."""

    pass


class Handler(Config):
    """Extends Config with request handling."""

    def handle(self, request: bytes) -> bytes:
        return b"OK"


def create_config(host: str, port: int = 8080) -> Config:
    """Create a new Config with defaults."""
    return Config(host, port)


def _helper():
    pass


async def async_fetch(url: str, timeout: int = 30) -> bytes:
    """Fetch data asynchronously."""
    pass


from dataclasses import dataclass


@dataclass
class Settings:
    """Application settings as a dataclass."""

    debug: bool = False
    verbose: bool = False


CONSTANT_TUPLE = (1, 2, 3)
