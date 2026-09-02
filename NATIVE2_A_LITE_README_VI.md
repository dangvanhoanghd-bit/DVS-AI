# NATIVE2-A Lite — Frame Ownership Telemetry

Bản này giữ nguyên BLAS single-thread của Test A và chỉ thêm telemetry fail-open.
Không thay đổi Decision Engine, không copy DataFrame, không thay đổi kết quả phân tích.

## File bằng chứng mới

`artifacts/runtime/frame_ownership.jsonl`

Các event chính:
- `frame_checkout`
- `engine_enter` / `engine_exit`
- `FRAME_CONCURRENT_USE`

`FRAME_CONCURRENT_USE` chỉ được ghi khi hai thread khác nhau đang hoạt động đồng thời trên cùng `(symbol, timeframe)` đang hoạt động chồng lấn (kể cả hai `scan_id` khác nhau) và có cùng `frame_id` hoặc `manager_id`. `np.shares_memory()` chỉ chạy trong trường hợp nghi ngờ hẹp này.

## Cách chạy

Chạy `START_DVS_AI_TEST_A_BLAS_1T.bat` như Test A trước đây. Sau crash hoặc burn-in đủ dài, nén nguyên `artifacts/runtime` và giữ cấu trúc session_id.
