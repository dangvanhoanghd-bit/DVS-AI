# Defect B Production Patch v2

Mục tiêu: quản lý lifecycle của QThread `dvs-learning-refresh` khi đóng ứng dụng.

Thay đổi chính:
- Giữ nguyên reference worker/thread hiện có.
- Worker có cooperative stop flag thread-safe và kiểm tra giữa từng stage.
- closeEvent phát stop, requestInterruption, quit và chờ tối đa 5000 ms.
- Nếu timeout hoặc exception: fail-closed, ghi telemetry, event.ignore(), không hủy QThread đang chạy.
- Chỉ tiếp tục shutdown sau khi thread đã dừng.
- Decision Engine không thay đổi.

Test: chạy START_DVS_AI.bat, đợi GUI hiện, đóng nút X trong lúc quét/refresh. Gửi lại artifacts/runtime và ảnh CMD.
