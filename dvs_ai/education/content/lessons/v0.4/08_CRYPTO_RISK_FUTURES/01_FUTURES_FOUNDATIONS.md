# 01 — Futures Foundations

## 1. Spot và futures khác nhau ở đâu?
Ở spot, người dùng mua/bán tài sản. Với futures, người dùng giao dịch một hợp đồng tạo **exposure** theo biến động giá. Vì vậy futures bổ sung các khái niệm mà người mới bắt buộc phải hiểu: margin, leverage, liquidation, funding và notional exposure.

## 2. Long và Short
- **Long:** có lợi khi giá tăng, bất lợi khi giá giảm.
- **Short:** có lợi khi giá giảm, bất lợi khi giá tăng.

Long/Short chỉ mô tả hướng exposure. Chúng không nói giao dịch đó tốt hay xấu.

## 3. Notional
Notional là giá trị thị trường mà vị thế đang kiểm soát.

Ví dụ giả định: một vị thế kiểm soát $1,000 giá trị BTC thì notional xấp xỉ $1,000, bất kể trader phải khóa bao nhiêu margin.

## 4. Ba khái niệm không được nhập làm một
`POSITION SIZE ≠ MARGIN ≠ RISK`

- Position size/notional: lượng exposure.
- Margin: collateral hỗ trợ vị thế.
- Planned risk: mức tổn thất trader chấp nhận theo kế hoạch.

## Kiểm tra nhanh
Một trader dùng ít margin có chắc đang chịu ít risk không?

**Đáp án:** Không. Cần biết position size, stop/invalidation, leverage, chi phí và cấu trúc vị thế.
