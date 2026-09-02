# Beta 4A RC4 — Unified Paper/Candidate lifecycle binding

## Luồng mới

1. Live Episode Capture tạo hoặc tìm đúng Candidate đã kích hoạt.
2. Exact `candidate_id`, `outcome_id`, `decision_id` và profile hashes được gắn vào kết quả phân tích.
3. Auto Paper chờ capture hoàn tất; không tạo lệnh tự động thiếu identity.
4. Paper `ACTIVE`, `TP1_HIT`, `CLOSED` được chiếu sang Candidate/Unified Outcome trong cùng transaction SQLite.
5. Learning tiếp tục chỉ đọc Unified Outcome, nhưng giờ nhận WIN/LOSS ngay khi Paper lifecycle kết thúc.

## Dữ liệu cũ

Chạy `AUDIT_RC4_LEGACY_PAPER_LINKS.bat` trước. File này chỉ phân tích và không sửa DB.

Nếu báo `ambiguous: 0`, chạy `APPLY_RC4_LEGACY_PAPER_LINKS.bat`. Công cụ chỉ liên kết các cặp duy nhất khớp đồng thời symbol, direction, toàn bộ trade plan và timestamp có kiểm soát UTC/UTC+7. Không có đối chiếu mờ và không sửa trường hợp mơ hồ.

Luôn sao lưu `data/dvs_paper_trades.db` trước khi chạy APPLY.
