# DVS AI Alpha 2.25.0 — Position Building Truth Audit

## Phương pháp

Đọc code thật, truy vết nguồn dữ liệu từ Binance provider tới Scanner, FinalizationWorker, MicrostructureService, FootprintOrchestrator, FootprintComposite và DecisionEngine; sau đó chạy test biên cho NaN, clipping, saturation, persistence và integration wiring.

## Inventory xác minh

| Khả năng | Trạng thái | Ghi chú |
|---|---|---|
| OI 15m | Có thật | Binance `openInterestHist`, đơn vị phần trăm |
| Funding | Có thật | `lastFundingRate * 100`, đơn vị điểm phần trăm |
| Delta ratio | Có thật | Từ aggressive buy/sell của aggTrades |
| CVD | Proxy | Hiện là trade delta snapshot; slope từ lịch sử delta ratio sau hydrate |
| Liquidation | Có điều kiện | Chỉ thật khi forceOrder/liquidation feed có dữ liệu; REST bootstrap thường không có |
| Absorption | Có thật | Proxy effort/result từ aggressive flow và micro-return |
| Persistence | Có thật | OI rolling history cho nhóm top-N đã hydrate |
| Acceleration | Có thật | Gia tốc độ lớn OI change |
| Iceberg Detection | Chưa có | Không được tuyên bố là đã triển khai |
| Queue Imbalance | Chưa có | Book imbalance có, nhưng không phải queue-level imbalance |

## Lỗi tích hợp đã xác nhận và sửa

### 1. Delta/CVD/Liquidation không đi vào Position Building ở lượt quét chuẩn

`ScannerService.scan_coin()` từng đọc các trường này từ `MarketSnapshot`, nhưng dataclass đó không chứa chúng. Kết quả là các giá trị mặc định bằng 0.

Sửa: sau khi top-N được `hydrate_microstructure()`, FinalizationWorker gọi `refresh_position_footprint()` để chạy lại Footprint bằng dữ liệu microstructure thật trước decision adjustment.

### 2. NaN history có thể tạo persistence giả

Các sample không hợp lệ từng bị xóa khỏi chuỗi, làm hai đoạn thời gian rời nhau nối liền. Sửa: giữ vị trí sample và thay bằng 0 để phá streak theo hướng fail-safe.

### 3. Input ngoài miền có thể bão hòa score

Delta/CVD ratio và absorption/liquidation context từng không được chuẩn hóa tại boundary. Sửa: ratio clamp [-1,1], score clamp [0,100].

## Giới hạn trung thực

- CVD hiện là proxy dựa trên aggTrades, chưa phải CVD bền vững từ WebSocket storage.
- Liquidation realtime phụ thuộc forceOrder feed; khi không có dữ liệu, metadata phải thể hiện unavailable.
- Book imbalance hiện tại không tương đương queue imbalance Level 3.
- Iceberg Detection chưa tồn tại.
- Engine là evidence layer, không được tự tạo TradeIntent hay lệnh LIVE.
