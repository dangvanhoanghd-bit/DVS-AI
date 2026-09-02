# DVS AI Alpha 2.7.2 — Retest Integrity & Risk Hardening

## Retest
- Không tạo retest giả khi dữ liệu dưới 35 nến.
- Breakout phải hoàn tất ít nhất hai nến trước nến hiện tại.
- Ưu tiên breakout hợp lệ gần nhất.
- Volume retest được so với baseline và volume nến breakout.
- Spread co lại giúp đạt tối đa 20/20.
- Retest chỉ đóng góp tối đa khoảng 6–7 điểm vào LOI/SOI.

## Smart Entry
- Trọng số cân bằng lại cho Panic, Weak Hand, Absorption, Fake Move,
  Retest, Alignment, Regime và Wyckoff.
- Phạt extension đúng hướng.
- Funding penalty tăng dần, không phạt kiểu bật/tắt.
- OI spike chỉ phạt nhẹ; Risk Engine vẫn là cổng chính.
- Absorption giữa range bị chiết khấu.
- Structure Test chỉ xác nhận chéo, không double-count đầy đủ.

## Futures Risk
- Dynamic liquidation buffer theo ATR.
- Xác minh hình học LONG/SHORT trước khi tính.
- Max safe leverage có trạng thái rõ khi stop không phải giới hạn.
- Position sizing tính cả phí và slippage.
- Có exposure cap cấu hình.
- Liquidation vẫn là xấp xỉ; tier MMR thực tế của Binance cần đối chiếu.

## Paper/Outcome
- Fill mô phỏng có slippage.
- Cập nhật incremental từ `last_checked_at`.
- Fetch 1m theo chunk.
- Hỗ trợ hàng đợi lớn hơn.
- Lệnh quá hạn chuyển EXPIRED.
- OutcomeTracker có retry/backoff cho rate limit và timeout.


## Alpha 2.7.3 — Decision & Structure Hardening

### Decision
- Confidence: 38% trend, 38% entry, directional agreement/conflict,
  6% Smart Money evidence, sau đó trừ 22% Risk Score.
- MTF conflict và Transition không được lên READY trực tiếp.
- Funding crowded-side bị chiết khấu trước Risk Engine.
- Spring/Upthrust chỉ được boost mạnh khi sweep đã xác nhận.
- Entry Zone và invalidation thích nghi theo ATR.

### Structure
- Sweep cần wick rejection và volume cao/thấp rõ ràng.
- Silent sweep được đánh giá mạnh khi wick sâu và volume cạn.
- Climax: volume cực cao nhưng range rất nhỏ.
- Easy Move: range lớn nhưng volume thấp.
- Wyckoff Test xem nhiều sự kiện gần nhất, xét recency, volume,
  spread và khoảng cách tới level.


## Alpha 2.7.4 — Plan Repair & Structure UX

- `_trade_plan()` tự sửa nhẹ khoảng cách entry/invalidation nếu hình học
  bị lệch do support/resistance bất thường, rồi tính lại TP và R:R.
- Nếu sau một lần sửa vẫn sai invariant, hệ thống tiếp tục raise ValueError
  để không che giấu lỗi nghiêm trọng.
- Structure Test dùng rolling support/resistance được tính một lần thay vì
  cắt DataFrame lặp lại ở từng candidate event.
- Detail và Liquidity/Wyckoff tab có tooltip giải thích Structure Test.
- Decision Reasons hiển thị Dynamic Buffer, Effective Stop Distance và
  trạng thái giới hạn đòn bẩy.


## Alpha 2.7.5 — Risk Diagnostics Transparency

Ba trường chẩn đoán Risk được hiển thị đồng thời ở Detail, Risk view và
Decision Reasons:

- `dynamic_buffer_used`: khoảng đệm thanh lý thích nghi theo ATR;
- `effective_stop_distance`: khoảng stop sau khi cộng phí và slippage;
- `leverage_constraint_state`: cho biết stop geometry có giới hạn đòn bẩy hay không.

Dynamic Buffer hiển thị cả dạng số thập phân và phần trăm.


## Alpha 2.7.6 — Deterministic Outcomes & Repair Audit

### Trade-plan repair
Mỗi lần `_trade_plan()` phải tự sửa hình học, hệ thống ghi warning log,
lưu `plan_repaired`, lưu `plan_repair_reason`, và hiển thị trong Detail.

### Slippage
Paper Trade dùng Gaussian noise có seed cố định theo trade ID, symbol và
direction. Kết quả thực tế hơn nhưng vẫn tái lập được. Database lưu cả
base slippage và realized slippage.

### Ambiguous candles
Khi nến 1m chạm cả TP/Stop mà không biết thứ tự, hệ thống lưu:
- `AMBIGUOUS_ENTRY_CANDLE`;
- `AMBIGUOUS_ACTIVE_CANDLE`;
- `AMBIGUOUS_AFTER_TP1`.

Ambiguous và expired không nằm trong mẫu số Win Rate/Calibration chính.

### Adaptive exit
Trailing stop và Wyckoff exit chưa bật mặc định. Classic TP/SL vẫn là
benchmark chính để đo chất lượng Entry.


## Alpha 2.7.7 — Execution Transparency & Repair Metrics

Paper Trade hiển thị `Slip %`; tooltip cho biết configured/realized
slippage, Seeded Gaussian model và outcome detail.

Learning Center hiển thị repair rate, Average/Median/P90 slippage,
ambiguous, expired và thời gian giữ lệnh trung bình. Plan đã repair được
lưu bằng tag `PLAN_REPAIRED`.

`resolve_mmr()` là điểm tích hợp cho bracket theo symbol/notional. Hiện
fixed MMR vẫn là fallback minh bạch: `FIXED_APPROXIMATION`.

Không giả định TP xảy ra trước Stop khi OHLC 1m không cho biết thứ tự.
Adaptive/Wyckoff exits tiếp tục tắt để giữ benchmark Classic.


## Alpha 2.7.8 — Outcome Consistency State Machine

`outcome_tracker.py` và Paper Trade Lab hiện dùng cùng triết lý:

```text
ACTIVE
  ├─ Stop → INVALID
  ├─ TP2 → TP2, có tính phần TP1
  └─ TP1 → TP1_HIT (trung gian)
                ├─ Stop → PARTIAL_STOP
                ├─ TP2 → TP2
                └─ cùng nến TP2/Stop → PARTIAL_AMBIGUOUS
```

TP1 không còn được ghi nhận là một chiến thắng cuối cùng trong tab Lịch sử
tín hiệu. Win Rate chỉ dùng `TP2`, `INVALID` và `PARTIAL_STOP`; thắng hay
thua dựa trên dấu của `r_multiple`. `AMBIGUOUS` và `EXPIRED` được thống kê
riêng và không làm tăng Win Rate.

Tỷ lệ chốt giống Paper Trade Lab:
- TP1 close fraction: 50%;
- runner fraction: 50%.


## Alpha 2.7.9 — Persistent Error Audit

Auto Paper Trade không còn gọi một method không tồn tại hoặc nuốt lỗi audit.

`SignalRecorder.record_error()` lưu có cấu trúc:

- timestamp;
- symbol và direction;
- exception type/message;
- stack trace;
- context của analysis;
- source (`AUTO_PAPER_TRADE` hoặc `AUTO_PAPER_WRAPPER`).

Database có bảng `error_logs` và index theo thời gian/source. Nếu chính thao
tác ghi database thất bại, hệ thống dùng Python logger và stderr fallback;
không còn `except Exception: pass` làm lỗi biến mất hoàn toàn.

`latest_errors()` và `error_stats()` đã sẵn sàng để nối vào Trung tâm lỗi
ở phiên bản UI kế tiếp.


## Alpha 2.8.0 — Single Source of Truth

### Confidence
Gauge `Confidence Score` hiển thị trực tiếp:

```python
analysis.confidence_score
```

UI không còn công thức Decision Score riêng. Tooltip ghi rõ dữ liệu đến từ
`DecisionEngine.combine()` và hiển thị các reason chính.

### Chart
Ở timeframe 15m, chart dùng trực tiếp:

- `trade_plan.entry_low`;
- `trade_plan.entry_high`;
- `trade_plan.invalidation`;
- `trade_plan.tp1`;
- `trade_plan.tp2`.

Khi TradePlan tồn tại, chart không vẽ thêm vùng Long/Short tự tính bằng hệ số
ATR cũ. Các timeframe khác chỉ giữ candidate zone dưới nhãn “tham khảo”.

### Outcome consistency
State machine TP1 → tiếp tục theo dõi → TP2/PARTIAL_STOP/AMBIGUOUS của bản
2.7.8 được giữ nguyên và có test hồi quy.


## Alpha 2.8.2 — Startup Hotfix

Sửa lỗi:

```text
ModuleNotFoundError: No module named 'annotations'
```

`main_window.py` đã xóa dòng không hợp lệ:

```python
import annotations
```

và giữ đúng dòng:

```python
from __future__ import annotations
```


## Alpha 2.8.3 — Trend Formation Hunter

Hệ thống tách hai khái niệm:

- Trend Strength: xu hướng đang mạnh đến đâu;
- Trend Maturity: xu hướng đã già và chạy xa đến đâu.

Maturity tổng hợp 15m/1h theo tỷ trọng 65/35 và phân loại:

- `UNFORMED`;
- `EARLY_FORMATION`;
- `FIRST_RETEST`;
- `CONFIRMED_TREND`;
- `LATE_TREND`;
- `EXHAUSTION`.

`READY` chỉ được phép khi maturity nằm trong vùng hình thành/xác nhận phù
hợp. Late Trend và Exhaustion chuyển thành `RUNNING`/`KHÔNG ĐUỔI GIÁ`.

Paper Trade lưu các tag maturity để Learning Center so sánh hiệu suất giữa
entry sớm và entry muộn bằng dữ liệu thực.


## Alpha 2.8.4 — Maturity Lifecycle Refinement

Maturity adjustment is now explicit and symmetric for LONG/SHORT:

- below 28: unformed, confidence ×0.82;
- 32–55: early-formation hunting zone, confidence ×1.14;
- 68–78: late penalty;
- above 78: READY is downgraded;
- above 82: exhaustion/RUNNING, no chasing.

The Regime badge tooltip is shortened to Strength, Maturity, Lifecycle and
15m/1h values.


## Alpha 2.8.5 — Maturity Quality Gate

Luồng duy nhất: Maturity 15m/1h → `_maturity_gate()` → lifecycle →
ngưỡng extension thích nghi → `_entry_status()` → `_quality_gate()`.

Giới hạn extension: UNFORMED 1.10 ATR, EARLY 1.55, CONFIRMED 1.80,
LATE 1.35, EXHAUSTION 0.90. FIRST_RETEST được tối đa 1.70 ATR.
Late/Exhaustion không thể tạo READY mới.


## Alpha 2.8.5.2 — Windows Locale Hotfix

Sửa lỗi Windows:

```text
UnicodeEncodeError: 'locale' codec can't encode character
```

Không còn đưa chữ tiếng Việt trực tiếp vào `strftime()`. Thời gian được định
dạng bằng chuỗi ASCII `%H:%M:%S`, sau đó mới ghép với nhãn `Hoàn tất`.


## Alpha 2.8.6 — Balanced Discovery Lab

Bản này giữ MAIN khắt khe nhưng mở riêng Discovery Shadow để tạo mẫu:

- MAIN: READY, Confidence ≥68, Entry ≥62, Risk ≤50, R:R ≥1.8.
- SHADOW: EARLY_FORMATION/FIRST_RETEST/CONFIRMED_TREND hoặc SETUP,
  Confidence ≥45, Entry ≥45, Risk ≤65, R:R ≥1.4.
- SHADOW không nhận RUNNING, LATE/EXHAUSTION hay Quality Gate bị BLOCK.

Mục tiêu là có mẫu Paper Trade để Learning Center đánh giá, nhưng vẫn không
quay lại lỗi đuổi theo xu hướng.


## Alpha 2.9.0 — Quantum Learning Lab

Đây là thuật toán quantum-inspired Genetic Algorithm, không phải máy tính lượng tử. Bộ tối ưu đọc các lệnh Paper đã đóng, chia theo thời gian thành train/validation và chỉ đề xuất cấu hình khi kết quả validation ổn định. MAIN không tự thay đổi. Shadow có thể được áp dụng thủ công với giới hạn thay đổi mỗi chu kỳ và backup config.


## Alpha 2.9.1 — Quantum Safety Audit

Bổ sung lớp giám sát cho Quantum Learning Lab:

- kiểm tra tĩnh không có đường ghi `main_*`;
- walk-forward split được đóng gói thành `_chronological_split()`;
- validation phải có tối thiểu số mẫu được chọn;
- Average R validation không được giảm;
- drawdown validation không được tăng quá giới hạn;
- cải thiện validation phải vượt cả ngưỡng tối thiểu và search penalty.

Search penalty tăng theo số tổ hợp được thử:

```text
0.22 × log(1 + population_size × generations)
```

Đây không loại bỏ hoàn toàn multiple-comparison risk, nhưng khiến optimizer
khó báo an toàn chỉ nhờ một kết quả may mắn trên validation nhỏ.


## Alpha 2.9.2 — Market Bias & Maturity Caps

### Maturity Confidence Caps
- LATE: tối đa 65;
- maturity >78: tối đa 60;
- EXHAUSTION: tối đa 45.

MAIN đã được bảo vệ bởi status gate; trần mới chủ yếu giúp Shadow và UI không
diễn giải một setup muộn thành “confidence rất cao”.

### Market Bias Hard Gate
Market Bias được tính sau khi quét đủ BTC và breadth altcoin:

- STRONG_LONG / LONG;
- NEUTRAL;
- SHORT / STRONG_SHORT.

Hướng ngược STRONG bias bị WAIT và Confidence ≤49. Counter-trend chỉ được
giữ ở SETUP/Shadow khi có Wyckoff event + Test/Break + CMF + EMA20 xác nhận.

Auto Paper chỉ chạy sau khi Market Bias Gate đã áp dụng.

### Quantum Interpretation
Báo cáo tách MAIN và SHADOW. Shadow là phòng thí nghiệm thu thập mẫu biên,
do đó lệnh muộn trong Shadow không được diễn giải như lỗi bảo vệ vốn MAIN.


## Alpha 2.9.3 — Direction Confirmation V3

Direction is no longer accepted only because its aggregate Trend+Entry score is
larger. The chosen side must also pass an evidence gate.

### LONG evidence
- CMF15m/1h positive;
- price above EMA20;
- RSI holding the neutral zone;
- Spring/Sweep bottom;
- Test after Spring;
- confirmed breakout;
- LONG alignment/regime.

### SHORT evidence
- CMF15m/1h negative;
- price below EMA20;
- RSI losing the neutral zone;
- Upthrust/Sweep top;
- Test after Upthrust;
- confirmed breakdown;
- SHORT alignment/regime.

Upthrust alone can no longer create a valid SHORT when CMF remains positive and
price has not lost EMA20.

Gate states:
- CONFIRMED ≥72;
- WATCH 55–71;
- BLOCK <55.

BLOCK forces WAIT and Confidence ≤49. WATCH downgrades READY to SETUP and caps
Confidence at 64.

CSV export includes the full diagnostic snapshot required for deeper audit.


## Alpha 2.9.4 — Quantum Optimizer Dashboard

The optimizer now runs in a background QThread. The dedicated dashboard shows
generation progress, best/average fitness, evaluation count, bounded cache,
elapsed time, ETA, and a live fitness chart.

Memory safeguards:
- bounded LRU fitness cache;
- population/scored/pool collections released each generation;
- configurable garbage collection interval;
- cache cleared before and after each run;
- safe cancellation between generations.

MAIN remains locked. Only validated SHADOW proposals can be applied manually.


## Alpha 2.9.5 — Opportunity Quality Gate

Confidence is not globally loosened. A maximum five-point recovery is allowed
only when Direction Confirmation, Market Bias, lifecycle, liquidation safety
and maturity all agree. WAIT/RUNNING and hard blocks remain unchanged.

The completed universe is then ranked separately by LONG and SHORT. Paper
Trade accepts only the highest-quality candidates:
- MAIN: Top 3 per direction;
- SHADOW: Top 5 per direction;
- minimum Opportunity Score: 52.

This controls concentration but is not a true return-correlation engine.


## Alpha 2.10.0 — Microstructure Foundation

Phase 1 introduces a conservative public-data microstructure layer:

- Binance Futures L2 depth snapshot;
- recent aggregate trades;
- aggressive buy/sell notional;
- trade Delta and CVD proxy;
- OFI proxy;
- absorption/exhaustion;
- bid/ask wall concentration;
- position-building and Effort-vs-Result;
- Composite Operator Score.

Only the top-ranked symbols are hydrated to avoid multiplying REST calls over
the full universe. Microstructure can confirm or conflict with an opportunity,
then the universe is re-ranked before Paper Trade.

Important limitations:
- public depth is Level 2, not identity-level Level 3;
- one REST snapshot cannot prove spoofing;
- realtime liquidation requires Binance forceOrder WebSocket;
- this release does not enable live trading or alter MAIN safety rules.


## Alpha 2.10.1 — Microstructure Integration

Microstructure now acts as an explicit post-decision confirmation/denial layer.

Gate levels:
- STRONG_CONFIRMATION
- CONFIRMATION
- WEAK_CONFIRMATION
- OBSERVE
- WEAK_CONFLICT
- CONFLICT
- STRONG_CONFLICT

Configured defaults:
- weight 0.25;
- maximum confirmation bonus +6;
- maximum conflict penalty -12;
- SHADOW minimum COS 48.

The layer cannot promote WAIT/RUNNING into READY and cannot bypass Maturity,
Market Bias, liquidation or existing Decision gates.

SHADOW rejection reasons are normalized for Learning Center:
MICROSTRUCTURE_CONFLICT, MICRO_LOW_COS, MICRO_OPPOSING_BIAS,
MICRO_NO_CONFIRMATION, LOW_ABSORPTION, LOW_POSITION_BUILDING and
LOW_ORDERFLOW_CONFIRMATION.

Order Block mitigation, FVG and BOS/CHOCH remain planned for Phase 2.11.


## Alpha 2.11.1 — OrderBlock Engine V2

OrderBlockEngine is now fully implemented under the frozen footprint
architecture. It detects bullish and bearish origin candles before impulsive
displacement, confirms structural breaks, tracks the block lifecycle and emits
explainable immutable evidence.

Returned diagnostics include:

- direction and state;
- zone boundaries and midpoint;
- age;
- detection confidence;
- freshness;
- mitigation quality;
- reaction quality;
- impulse and volume scores;
- overall quality;
- lifecycle context;
- invalidation and Breaker status.

This engine remains evidence-only. It cannot create or modify READY, SETUP,
WAIT or RUNNING and does not affect Decision Engine until the Footprint
Composite sprint.


## Alpha 2.11.2 — Scanner Infrastructure V2

The scan worker now executes a bounded number of symbols concurrently. The
default is six workers, deliberately below aggressive values to reduce Binance
rate-limit pressure.

OHLCV uses Binance Futures REST directly, with:

- classified errors;
- retry/backoff;
- thread-local sessions;
- connection pooling;
- bounded TTL caching;
- one shared frame per symbol/timeframe within the cache window.

`INSUFFICIENT_HISTORY` is a skip condition, not a broken algorithm. Increase
`scan_workers` cautiously; values above 8 may create more retries than useful
speed on unstable networks.


## Alpha 2.12.0 — Phase 3 Smart Money Footprint

Implemented evidence engines:

- Order Block V2;
- FVG V2;
- BOS/CHOCH;
- Liquidity Sweep;
- Structure Lifecycle;
- weighted Smart Money Footprint Composite.

The composite requires independent agreement. A single indicator cannot produce
`strong_confirmation`. Decision Engine is deliberately unchanged in this
release, so the new layer can collect Paper/diagnostic evidence before it is
allowed to influence READY/SETUP/WAIT/RUNNING.


## Alpha 2.13.0 — Futures Execution Foundation

A separate execution boundary now exists under `dvs_ai/execution/`.

Safety rules:

- default mode is PAPER;
- TESTNET and LIVE require explicit confirmation;
- LIVE is disabled by default;
- Decision Engine cannot call Binance directly;
- all intents pass OrderValidator and Circuit Breaker;
- reduce-only exits may still pass when new risk is blocked;
- every result is written to SQLite execution audit;
- unique clientOrderId values prevent accidental duplicate submissions.

The CloddsBot project was used as an architectural reference. Its TypeScript
runtime was not embedded into DVS AI; the required concepts were reimplemented
as native Python modules compatible with the existing PySide6 application.
