# TEST A — BLAS/NumPy single-thread cohort

Mục tiêu: kiểm tra liệu nested native parallelism (ThreadPoolExecutor của scanner × BLAS/OpenMP/NumExpr) có liên quan đến native access violation hay không.

## Phạm vi thay đổi

Chỉ launcher `START_DVS_AI_TEST_A_BLAS_1T.bat` đặt bốn biến môi trường trước khi Python import NumPy/pandas:

- `OMP_NUM_THREADS=1`
- `MKL_NUM_THREADS=1`
- `OPENBLAS_NUM_THREADS=1`
- `NUMEXPR_NUM_THREADS=1`

Không sửa mã Python, scanner, Decision Engine, PERF1, NET1 hoặc FIX-DUMP.

## Cách chạy

1. Giải nén vào thư mục mới.
2. Chạy `START_DVS_AI_TEST_A_BLAS_1T.bat` — không chạy launcher thường cho cohort Test A.
3. Giữ nguyên universe, chu kỳ scan và cấu hình giống các phiên crash trước.
4. Thực hiện tối thiểu 3 phiên, khuyến nghị 5 phiên.
5. Mỗi phiên phải chạy ít nhất bằng số chu kỳ/thời gian của phiên từng crash. Một phiên ngắn sạch không được tính là bằng chứng.
6. Nếu crash/treo, để tiến trình tồn tại thêm 60–90 giây khi có thể để FIX-DUMP ghi nhiều stack.

## Bằng chứng cần giữ riêng theo session_id

Giữ nguyên cấu trúc thư mục, không trộn các phiên:

```
TEST_A_EVIDENCE/
  <session_id_1>/
    SESSION_SUMMARY.txt
    native_fault.log
    freeze_dump.log
    freeze_dump_metadata.json
    heartbeat.json
    scheduler_drift.jsonl
    runtime_status.json
  <session_id_2>/
    ...
```

`SESSION_SUMMARY.txt` cần ghi:

- session_id
- PID
- thời điểm bắt đầu/kết thúc
- tổng thời gian chạy
- số vòng scan hoàn tất
- universe size
- kết quả: CLEAN / NOT_RESPONDING / NATIVE_CRASH / OTHER
- ghi chú điều kiện mạng và thao tác người dùng

## Cách diễn giải

- Crash vẫn xuất hiện cùng stack: giả thuyết nested BLAS parallelism yếu đi; chuyển sang audit DataFrame ownership.
- Một phiên sạch: bằng chứng yếu.
- 3–5 phiên sạch đủ dài: bằng chứng mạnh rằng giới hạn native thread làm giảm xác suất crash, chưa chứng minh nguyên nhân duy nhất.
