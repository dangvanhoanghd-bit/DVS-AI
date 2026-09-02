from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Beta4AGateError(RuntimeError):
    """Structured hard-block or operational refusal emitted by a Beta 4A gate."""

    code: str
    message: str

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"
