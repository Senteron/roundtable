"""In-memory provider for tests.

FakeProvider is the single most important test fixture. The
dispatcher, framing, schemas, and N-1 tolerance are all testable
against this without burning credits or introducing flakiness.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from .base import InvalidProviderOutput, ProviderResponse


@dataclass
class FakeProvider:
    """Configurable fake.

    behavior:
        - "echo": returns f"<{name}> {prompt[:200]}" after delay_seconds.
        - "timeout": sleeps longer than any reasonable timeout to
          force asyncio.TimeoutError downstream.
        - "error": raises RuntimeError(error_message).
        - "invalid_output": raises InvalidProviderOutput, which the
          dispatcher maps to ErrorClass.INVALID_OUTPUT.
        - "fixed": returns fixed_response verbatim.
    """

    name: str
    context_window_tokens: int = 100_000
    behavior: str = "echo"
    delay_seconds: float = 0.0
    fixed_response: str = ""
    error_message: str = "fake provider error"
    cost_usd: float | None = 0.0001
    last_prompt: str = field(default="", init=False)

    async def call(
        self,
        prompt: str,
        timeout_seconds: float,
    ) -> ProviderResponse:
        self.last_prompt = prompt
        start = time.monotonic()

        if self.behavior == "timeout":
            await asyncio.sleep(timeout_seconds + 10)
            text = "should never get here"
        elif self.behavior == "error":
            await asyncio.sleep(self.delay_seconds)
            raise RuntimeError(self.error_message)
        elif self.behavior == "invalid_output":
            await asyncio.sleep(self.delay_seconds)
            raise InvalidProviderOutput(self.error_message)
        elif self.behavior == "echo":
            await asyncio.sleep(self.delay_seconds)
            text = f"<{self.name}> {prompt[:200]}"
        elif self.behavior == "fixed":
            await asyncio.sleep(self.delay_seconds)
            text = self.fixed_response
        else:
            raise ValueError(f"unknown FakeProvider behavior: {self.behavior!r}")

        elapsed = time.monotonic() - start
        return ProviderResponse(
            text=text,
            elapsed_seconds=elapsed,
            estimated_cost_usd=self.cost_usd,
        )
