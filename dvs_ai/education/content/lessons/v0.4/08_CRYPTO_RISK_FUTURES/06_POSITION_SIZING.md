# 06 — Position Sizing

## Risk-first sequence
1. Xác định equity/account context.
2. Xác định mức tiền tối đa chấp nhận mất cho trade.
3. Xác định invalidation/stop distance.
4. Từ đó suy ra position size.
5. Kiểm tra margin/leverage/liquidation/cost constraints.
6. Giảm size hoặc bỏ trade nếu cấu trúc không an toàn.

## Công thức giáo dục đơn giản
Với instrument tuyến tính và bỏ qua chi phí:

`position quantity ≈ monetary risk / |entry - stop|`

Ví dụ giả định:
- risk budget: $10
- entry: $100
- stop: $98
- loss per unit: $2

Quantity khái niệm ≈ 10 / 2 = 5 units.

Thực tế cần điều chỉnh theo contract specification, fees, slippage và quy tắc sàn.

## Anti-pattern
`available margin → maximum position`

Available margin không phải risk budget.

## Quy tắc
Nếu không xác định được invalidation hợp lý, không có cơ sở tốt để suy ra position size. **STAND ASIDE** là lựa chọn hợp lệ.
