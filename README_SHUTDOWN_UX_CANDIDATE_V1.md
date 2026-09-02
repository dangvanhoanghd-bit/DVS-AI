# RC6.4.7H-r2 — Shutdown UX Candidate V1

## Mục tiêu

Loại bỏ yêu cầu người dùng phải bấm đóng lần hai khi QThread Registry còn survivor sau cửa sổ fail-closed 5 giây.

## Luồng mới

```text
closeEvent
→ cooperative shutdown hiện có
→ registry wait tối đa 5 giây
→ nếu còn survivor: event.ignore + trạng thái CLOSING
→ QTimer 250 ms snapshot registry (không wait, không terminate)
→ survivor_count = 0
→ tự gọi close và tiếp tục phần final cleanup
```

## Telemetry mới

- `shutdown_ux_poll_started`
- `shutdown_ux_poll_tick` với `measurement_ms`, `budget_ms`, `budget_exceeded`
- `shutdown_ux_poll_failed`
- `shutdown_ux_registry_clear`

## Giới hạn có chủ đích

Candidate này không cung cấp nút **Hủy đóng** thực sự. Tại thời điểm registry polling bắt đầu, nhiều service/timer/thread đã nhận lệnh dừng không thể đảo ngược an toàn. Một nút Cancel lúc đó sẽ tạo trạng thái chạy nửa vời. Muốn có Cancel đúng nghĩa cần một refactor hai pha: `PREPARE_TO_CLOSE` có thể đảo ngược, sau đó mới `COMMIT_CLOSE`.

## Trạng thái xác minh

- Source implementation: PASS
- Python compile: PASS
- Release identity test: PASS
- Runtime verification: PENDING
