# Defect B Production Patch v5

Mục tiêu: gọi shutdown Outcome Resolution ngay đầu `closeEvent()` và truyền cooperative cancellation/deadline xuống các vòng lặp nội bộ của ba service.

Các điểm chính:
- Dừng `outcome_resolution_timer` và gọi coordinator `close(timeout_ms=5000)` ngay sau snapshot đầu closeEvent.
- Không xóa cancellation token trong worker slot; token chỉ được clear trước một dispatch mới để tránh race shutdown/queued-slot.
- OutcomeTracker: cancel trong retry/backoff, trước provider fetch, giữa chunk và giữa candle.
- PaperTradeService: cancel giữa row, chunk fetch và candle evaluation; InterruptedError không bị nuốt.
- CandidateOutcomeResolver: cancel trong retry/backoff, trước provider fetch, giữa row và candle; InterruptedError không bị chuyển thành lỗi record.
- Fail-closed: quá 5 giây thì từ chối đóng, không ghi shutdown sạch giả.

Decision Engine không thay đổi.
