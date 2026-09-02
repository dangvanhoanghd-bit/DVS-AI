from __future__ import annotations

import time
from dataclasses import dataclass


class DeadlineExceeded(TimeoutError):
    """Raised when an explicit monotonic deadline budget is exhausted."""


@dataclass(frozen=True)
class DeadlineBudget:
    deadline_at: float
    label: str = "operation"

    @classmethod
    def start(cls, seconds: float, *, label: str = "operation") -> "DeadlineBudget":
        if seconds <= 0:
            raise ValueError("deadline seconds must be > 0")
        return cls(time.monotonic() + float(seconds), label)

    def remaining(self) -> float:
        return max(0.0, self.deadline_at - time.monotonic())

    def expired(self) -> bool:
        return self.remaining() <= 0.0

    def raise_if_expired(self) -> None:
        if self.expired():
            raise DeadlineExceeded(f"{self.label} deadline exceeded")

    def child(self, seconds: float, *, label: str) -> "DeadlineBudget":
        """Create a child budget bounded by this budget's absolute deadline."""
        return DeadlineBudget(min(self.deadline_at, time.monotonic() + float(seconds)), label)
