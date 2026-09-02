# RC6.4.6A Windows Validation Checklist

1. Start while provider circuit is OPEN.
2. Verify badge reads `Provider: BACKOFF ...` and countdown decreases.
3. Click `Kiểm tra API` while OPEN.
   - Friendly message appears immediately.
   - No new real `/fapi/v1/time` request is emitted.
4. Click `Nạp Universe` while OPEN.
   - GUI stays responsive.
   - Message says Binance is in backoff and restart is unnecessary.
5. At expiry, verify badge changes to `Provider: PROBING`.
6. Verify telemetry records exactly one half-open probe.
7. On probe success, verify badge changes to `Provider: ONLINE`.
8. On 418/429, verify badge returns to BACKOFF using raw Retry-After.
