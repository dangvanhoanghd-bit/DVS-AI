import threading
import time

from dvs_ai.runtime.provider_circuit import (
    ProviderGlobalCircuitBreaker,
    ProviderCircuitShortCircuited,
)


def test_e_exactly_one_half_open_probe_claimed():
    circuit = ProviderGlobalCircuitBreaker()
    permit = circuit.before_request(endpoint="/seed", phase="test", symbol="")
    circuit.observe_rate_limit(
        status_code=418,
        retry_after_raw_seconds=0.01,
        endpoint="/seed",
        phase="test",
        symbol="",
        permit=permit,
    )
    time.sleep(0.02)
    barrier = threading.Barrier(6)
    results = []
    lock = threading.Lock()

    def worker():
        barrier.wait()
        try:
            claimed = circuit.before_request(endpoint="/probe", phase="test", symbol="")
            value = "probe" if claimed.is_probe else "normal"
        except ProviderCircuitShortCircuited as exc:
            value = exc.code
        with lock:
            results.append(value)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert results.count("probe") == 1
    assert results.count("PROVIDER_HALF_OPEN_PROBE_ALREADY_CLAIMED") == 5


def test_f_concurrent_rate_limits_preserve_max_blocked_until():
    circuit = ProviderGlobalCircuitBreaker()
    permits = [circuit.before_request(endpoint=f"/{i}", phase="test", symbol="") for i in range(3)]
    barrier = threading.Barrier(3)

    def worker(raw, permit):
        barrier.wait()
        circuit.observe_rate_limit(
            status_code=418,
            retry_after_raw_seconds=raw,
            endpoint="/rate",
            phase="test",
            symbol="",
            permit=permit,
        )

    before = time.monotonic()
    threads = [
        threading.Thread(target=worker, args=(raw, permit))
        for raw, permit in zip((100.0, 150.0, 120.0), permits)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    remaining = circuit.snapshot()["remaining_seconds"]
    assert 149.0 <= remaining <= 150.5
    assert circuit.snapshot()["state"] == "OPEN"
    assert time.monotonic() >= before
