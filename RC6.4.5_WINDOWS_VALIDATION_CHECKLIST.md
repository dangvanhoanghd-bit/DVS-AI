# RC6.4.5 Windows Validation Checklist

1. Launch DVS AI and trigger “Nạp Universe”.
2. Confirm the window can be moved, resized, and tabs can be changed while the request is pending.
3. Inspect `artifacts/runtime/provider_evidence.jsonl`: universe provider calls must not report `thread_name="MainThread"`.
4. Inspect `artifacts/runtime/universe_loader.jsonl` for started → finished/failed → finalized.
5. Confirm when idle: `universe_load_active_count=0` and started count equals finalized count.
6. Repeatedly click “Nạp Universe” during an active load; confirm only one provider operation runs and a single-flight rejection event is emitted.
7. Use a mock/local HTTP server or injected transport to return HTTP 418 with `Retry-After: 300`; do not intentionally rate-limit Binance.
8. During the mock delay, confirm no Windows “Not Responding” state and no event-loop lag matching the provider deadline.
9. After successful loading, confirm the deferred scan starts once and only once.
10. Continue the separate ≥3-hour RC6.4.4 scan-lifecycle burn-in; do not merge its conclusion with RC6.4.5 startup validation.
