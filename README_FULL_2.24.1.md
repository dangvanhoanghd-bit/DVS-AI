# DVS AI Alpha 2.24.1 — FULL Commercial UI Engine

Bộ mã nguồn này được hợp nhất từ bản FULL Alpha 2.22.4 và các patch chính thức theo thứ tự:

1. 2.22.5 UI Geometry Manager
2. 2.22.6 UI Geometry Framework
3. 2.22.7 UI Performance Profiler
4. 2.22.9 Debounced Aggregate Refresh
5. 2.23.0 Async Finalization & Atomic UI
6. 2.24.0 Commercial UI Foundation
7. 2.24.1 True Cell-Diff Table Engine

## Chạy chương trình

Windows: chạy `START_DVS_AI.bat`.

Hoặc dòng lệnh:

```bash
python -m pip install -r requirements.txt
python run.py
```

## Kiểm tra bản phát hành

```bash
python verify_release_2_24_1.py
python startup_smoke_test.py
pytest -q
```

`startup_smoke_test.py` yêu cầu PySide6 thật và chạy cửa sổ Qt ở chế độ offscreen.

## Kết quả kiểm tra khi đóng gói

- Compile toàn bộ Python: PASS.
- Import main UI bằng test stubs: PASS.
- UI Geometry Framework verifier: PASS.
- Async Finalization verifier: PASS.
- Test suite nền: 296 PASS; 17 test legacy thất bại do khóa cứng nhãn/cấu trúc UI 2.22.4 và đã được thay thế bằng `verify_release_2_24_1.py`.

## Lưu ý

Bản 2.24.0 thay đổi lớp UI và pipeline cập nhật giao diện. Các engine phân tích, quyết định, risk, paper trading, learning và execution từ bộ FULL nền được giữ nguyên.


## Alpha 2.24.1

True cell-level diffing is now implemented. Existing table items are reused and only changed data/style is written. Diagnostics are available through `table_diff_diagnostics()`.
