# DVS AI Alpha 2.24.0 – Commercial UI Engine

## File nâng cấp
- `main_window.py`: thay cho file `dvs_ai/ui/main_window.py` hiện tại.

## Thay đổi chính
- Chuẩn hóa tên ứng dụng và phiên bản 2.24.0 tại một nhóm hằng số duy nhất.
- Commercial status strip: trạng thái engine, worker, đồng hồ và scan info.
- Tự cập nhật trạng thái `READY / BUSY`, `idle / scanning / finalizing`.
- Lưu và khôi phục geometry cửa sổ, tab đang mở và trạng thái Auto Scan bằng `QSettings`.
- Phím tắt:
  - Ctrl+R: quét dữ liệu
  - Ctrl+Shift+R: quét lại lỗi
  - Ctrl+E: xuất CSV
  - Ctrl+L: focus tìm coin
  - Esc: dừng tác vụ
- Bổ sung tooltip cho các nút chính.
- Polish theme: tab hover, pane border, scrollbar và tooltip thương mại.
- Giữ nguyên toàn bộ scan engine, async finalization, paper trading, history, quantum optimizer và các tab phân tích.

## Kiểm tra đã thực hiện
- `python -m py_compile main_window.py`: PASS.

## Cách dùng
1. Sao lưu file `dvs_ai/ui/main_window.py` hiện tại.
2. Chép file mới vào đúng đường dẫn trên.
3. Chạy ứng dụng như bình thường.

## Lưu ý
Bản này được nâng trực tiếp từ `main_window(6).py` – Alpha 2.23.0 Async Finalization. Kiểm tra cú pháp đã đạt, nhưng kiểm thử runtime đầy đủ cần chạy trong project có đủ module `dvs_ai` và PySide6.
