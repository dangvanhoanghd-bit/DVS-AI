from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass

from dvs_ai.services.provider_evidence_telemetry import PROVIDER_EVIDENCE


class ProviderCircuitShortCircuited(RuntimeError):
    def __init__(self, code: str, remaining_seconds: float = 0.0) -> None:
        self.code = code
        self.remaining_seconds = max(0.0, float(remaining_seconds))
        super().__init__(f"{code}: provider circuit unavailable for {self.remaining_seconds:.3f}s")


@dataclass(frozen=True)
class CircuitPermit:
    probe_token: str | None = None

    @property
    def is_probe(self) -> bool:
        return self.probe_token is not None


class ProviderGlobalCircuitBreaker:
    """Process-wide atomic circuit for Binance 418/429 responses.

    All state transitions and blocked_until read/modify/write operations are
    protected by one non-reentrant Lock. Exactly one caller may claim HALF_OPEN.
    """

    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = self.CLOSED
        self._blocked_until = 0.0
        self._probe_token: str | None = None
        self._probe_claimed_by: int | None = None

    def snapshot(self) -> dict:
        with self._lock:
            now = time.monotonic()
            return {
                "state": self._state,
                "blocked_until_monotonic": self._blocked_until,
                "remaining_seconds": max(0.0, self._blocked_until - now),
                "probe_claimed_by": self._probe_claimed_by,
            }

    def before_request(self, *, endpoint: str, phase: str, symbol: str) -> CircuitPermit:
        now = time.monotonic()
        event = None
        fields = {}
        with self._lock:
            if self._state == self.CLOSED:
                return CircuitPermit()
            if self._state == self.OPEN and now < self._blocked_until:
                remaining = self._blocked_until - now
                code = "PROVIDER_CIRCUIT_OPEN"
            elif self._state == self.HALF_OPEN:
                remaining = max(0.0, self._blocked_until - now)
                code = "PROVIDER_HALF_OPEN_PROBE_ALREADY_CLAIMED"
            else:
                # Atomic OPEN -> HALF_OPEN claim. Only this caller gets a token.
                token = uuid.uuid4().hex
                self._state = self.HALF_OPEN
                self._probe_token = token
                self._probe_claimed_by = threading.get_ident()
                event = "provider_circuit_half_open"
                fields = {"probe_token": token, "probe_claimed_by": self._probe_claimed_by}
                permit = CircuitPermit(token)
                remaining = 0.0
                code = ""
        if event:
            PROVIDER_EVIDENCE.emit(event, endpoint=endpoint, phase=phase, symbol=symbol, **fields)
            PROVIDER_EVIDENCE.emit("provider_half_open_probe_started", endpoint=endpoint, phase=phase, symbol=symbol, **fields)
            return permit
        PROVIDER_EVIDENCE.emit(
            "provider_request_short_circuited", endpoint=endpoint, phase=phase,
            symbol=symbol, reason=code, remaining_seconds=round(remaining, 3),
        )
        raise ProviderCircuitShortCircuited(code, remaining)

    def observe_rate_limit(
        self, *, status_code: int, retry_after_raw_seconds: float | None,
        endpoint: str, phase: str, symbol: str, permit: CircuitPermit,
    ) -> None:
        now = time.monotonic()
        raw = max(0.0, float(retry_after_raw_seconds or 0.0))
        candidate = now + raw
        with self._lock:
            previous_state = self._state
            previous_until = self._blocked_until
            self._blocked_until = max(self._blocked_until, candidate)
            self._state = self.OPEN
            self._probe_token = None
            self._probe_claimed_by = None
            extended = self._blocked_until > previous_until
        event = "provider_circuit_opened" if previous_state == self.CLOSED else "provider_circuit_extended"
        PROVIDER_EVIDENCE.emit(
            event, endpoint=endpoint, phase=phase, symbol=symbol,
            status_code=int(status_code), retry_after_raw_seconds=raw,
            blocked_until_monotonic=round(self._blocked_until, 6),
            previous_blocked_until_monotonic=round(previous_until, 6),
            extended=extended, was_probe=permit.is_probe,
        )
        if permit.is_probe:
            PROVIDER_EVIDENCE.emit(
                "provider_half_open_probe_finished", endpoint=endpoint, phase=phase,
                symbol=symbol, outcome="rate_limited", status_code=int(status_code),
            )

    def on_success(self, *, permit: CircuitPermit, endpoint: str, phase: str, symbol: str) -> None:
        if not permit.is_probe:
            return
        closed = False
        with self._lock:
            if self._state == self.HALF_OPEN and self._probe_token == permit.probe_token:
                self._state = self.CLOSED
                self._blocked_until = 0.0
                self._probe_token = None
                self._probe_claimed_by = None
                closed = True
        PROVIDER_EVIDENCE.emit(
            "provider_half_open_probe_finished", endpoint=endpoint, phase=phase,
            symbol=symbol, outcome="success" if closed else "stale_probe",
        )
        if closed:
            PROVIDER_EVIDENCE.emit("provider_circuit_closed", endpoint=endpoint, phase=phase, symbol=symbol)


GLOBAL_PROVIDER_CIRCUIT = ProviderGlobalCircuitBreaker()
