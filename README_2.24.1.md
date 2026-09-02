# DVS AI Alpha 2.24.1 — True Cell-Diff Table Engine

## Phạm vi

Bản này hoàn thiện hạng mục đầu tiên sau Truth Audit của Alpha 2.24.0: bảng kết quả chỉ thay đổi dữ liệu và style của ô khi giá trị thực sự khác.

## Thay đổi đã triển khai

- Giữ lại `QTableWidgetItem` hiện có; chỉ tạo item khi ô chưa tồn tại.
- So sánh `DisplayRole` trước khi ghi dữ liệu.
- Diff alignment, background, foreground và bold font.
- Sửa thứ tự tô màu: base palette trước, semantic highlight sau.
- Thêm bộ đếm chẩn đoán:
  - `rows_inserted`
  - `cells_checked`
  - `cells_changed`
  - `items_created`
  - `style_changes`
  - `last_update_ms`
- Ghi thời gian cập nhật vào `UIPerformanceProfiler` với section `table_cell_diff`.
- Giữ nguyên cache `_row_by_symbol`, async finalization, aggregate debounce và dirty chart rendering.

## Ý nghĩa

Lần render đầu tiên của một dòng vẫn tạo tối đa 17 item. Các lần cập nhật sau giữ nguyên object và chỉ thay đổi ô có dữ liệu/style khác, giảm allocation, signal nội bộ và repaint không cần thiết.

## Xác minh

```bash
python verify_release_2_24_1.py
python -m compileall -q dvs_ai tests
```
