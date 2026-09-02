# DVS AI — CẬP NHẬT TÓM TẮT NGỮ CẢNH DỰ ÁN

## Scientific Safety Addendum cho Quantum Lab

**Trạng thái:** ĐÓNG BĂNG  
**Phạm vi:** Quantum Lab / Explainable Intelligence / Validation / Shadow Governance  
**Hiệu lực:** Trước khi viết `Quantum Dataset Factory`, Genetic Algorithm hoặc bất kỳ optimizer nào  
**Nguyên tắc nền:** Decision Engine quyết định; Quantum chỉ nghiên cứu. Quantum không có execution authority và không được tự sửa MAIN.

> Khối này phải được đặt trong mục **“Các nguyên tắc/bất biến đã ĐÓNG BĂNG”** của tài liệu ngữ cảnh dự án, cùng nhóm với các bất biến gốc. Mọi phiên audit hoặc triển khai Quantum về sau phải kiểm tra đầy đủ QG-01 → QG-16.

---

## Lý do đóng băng

Quantum có thể tạo ra kết quả trông rất thuyết phục nhưng sai về mặt khoa học nếu dữ liệu chưa trưởng thành, chia dữ liệu sai theo thời gian, thử quá nhiều cấu hình, tái sử dụng holdout, dùng thông tin tương lai, trộn các policy không tương thích hoặc coi mẫu tương quan là độc lập.

Vì vậy Quantum phải là một **hệ thống nghiên cứu định lượng có governance**, không phải một công cụ tự động “tìm tham số tốt nhất”.

Luồng quyền hạn duy nhất được phép:

```text
Decision Engine (frozen)
→ Paper Trade / Outcome Evidence
→ Quantum Research
→ Validation
→ Sealed Governance Artifact
→ SHADOW
→ Human Approval
→ MAIN
```

MAIN không bao giờ bị Quantum ghi đè tự động.

---

# CÁC BẤT BIẾN QUANTUM ĐÃ ĐÓNG BĂNG

## QG-01 — Data Integrity Gate

Quantum chỉ được nghiên cứu khi toàn bộ kiểm tra integrity đạt PASS:

- không duplicate episode/outcome;
- chronology hợp lệ;
- outcome linkage hợp lệ;
- không orphan outcome;
- snapshot nhất quán;
- schema tương thích;
- lineage đầy đủ;
- checksum/provenance xác minh được.

Fail bất kỳ kiểm tra bắt buộc nào:

```text
QUANTUM_STATE = DATA_INTEGRITY_BLOCKED
OPTIMIZATION_ALLOWED = false
RECOMMENDATION_ALLOWED = false
SHADOW_APPLY_ALLOWED = false
```

Quantum chỉ được tạo báo cáo lỗi và hướng khắc phục.

---

## QG-02 — Resolved Outcome Gate và từ vựng schema

Phải dùng đúng schema thật của `candidate_outcomes.status`.

### Outcome đủ điều kiện làm nhãn tối ưu

```text
WIN
LOSS
```

### Outcome bị loại khỏi tập tối ưu

```text
AMBIGUOUS
EXPIRED_UNFILLED
PENDING
```

`AMBIGUOUS` phải bị loại **tường minh**, không được coi là WIN, LOSS hay một resolved sample dùng để học.

Quy tắc:

```text
AMBIGUOUS:
    ignore_for_optimization = true
    retain_for_data_quality_statistics = true

EXPIRED_UNFILLED:
    ignore_for_outcome_optimization = true
    retain_for_funnel_and_fill_statistics = true

PENDING:
    ignore_for_optimization = true
```

Không được tự thêm `BREAKEVEN` hoặc `INVALIDATED` vào logic nếu resolver/schema chưa được governance phê duyệt và migration chính thức.

---

## QG-03 — Sample Maturity và Cohort Coverage Gate

Ngưỡng theo resolved WIN/LOSS:

```text
resolved_n < 30:
    UNOBSERVABLE

30 <= resolved_n < 100:
    DESCRIPTIVE_ONLY

100 <= resolved_n < 300:
    RESEARCH_CANDIDATE_ONLY
    governance_promotion = false

resolved_n >= 300:
    eligible_for_full_validation_review
```

Đủ tổng mẫu chưa có nghĩa là đủ khoa học. Quantum còn phải kiểm tra coverage tối thiểu theo:

- direction;
- market regime;
- setup;
- time period;
- symbol/correlation cluster;
- policy scope.

Cohort thiếu mẫu vẫn phải trả về `UNOBSERVABLE`, kể cả khi tổng dataset lớn.

---

## QG-04 — Effective Sample Size Gate

Mọi readiness, confidence interval và validation phải báo cáo:

```text
raw_n
cluster_n
effective_n
```

Gate sử dụng cỡ mẫu bảo thủ, không dùng `raw_n` đơn thuần.

Tối thiểu hỗ trợ:

1. Kish Effective Sample Size khi có trọng số:
   `ESS = (Σw)^2 / Σ(w²)`.
2. Cluster-aware/block-aware ESS cho các episode phụ thuộc theo thời gian, BTC impulse, regime hoặc symbol correlation.

Ví dụ:

```text
raw_n = 300
effective_n = 47
```

Readiness phải được đánh giá theo `47`.

---

## QG-05 — Temporal Walk-Forward Only

Cấm random train/validation split cho dữ liệu thị trường.

Chỉ được dùng:

```text
past train
→ later validation
→ still-later locked holdout
```

Cho phép anchored hoặc rolling walk-forward, nhưng thứ tự thời gian không được đảo và không được shuffle.

---

## QG-06 — Purge và Embargo

Các sample có horizon chồng lấn không được xuất hiện ở hai tập khác nhau.

Mỗi fold phải có:

- purge window dựa trên evaluation/outcome horizon;
- embargo window phù hợp sau biên train;
- kiểm tra overlap tự động;
- audit record của sample bị loại.

Violation:

```text
VALIDATION_STATUS = LEAKAGE_BLOCKED
```

---

## QG-07 — Locked Holdout Lifecycle / Burn Policy

Locked holdout chỉ được mở đúng một lần.

Manifest bắt buộc có:

```text
holdout_id
created_at
sealed_at
opened_at
consumed
dataset_cutoff
policy_scope_id
```

Sau khi mở:

```text
consumed = true
```

Holdout đã consumed:

- không được tái sử dụng để chọn candidate;
- không được dùng lại trong vòng re-optimize sau;
- chỉ được lưu làm archive/audit evidence.

Mỗi chu kỳ đánh giá cần holdout mới phải dùng **fresh rolling holdout** chưa từng bị mở.

**QG-14 không định nghĩa lại quy tắc holdout; QG-14 chỉ tham chiếu QG-07 để tránh trùng lặp tài liệu.**

---

## QG-08 — Multiple-Comparison Control trong một lần chạy

Không được dùng quy tắc “best validation score wins”.

Bắt buộc có các lớp bảo vệ:

- governance whitelist giới hạn search space;
- optimizer chỉ nhìn train;
- validation chọn candidate;
- locked holdout chỉ mở sau khi candidate/protocol đã khóa;
- block/cluster bootstrap hoặc null distribution phù hợp;
- điều chỉnh multiple testing phù hợp với protocol;
- stability/sensitivity quanh vùng tham số lân cận;
- ghi đầy đủ số candidate/hypothesis/evaluation đã thử.

Kỹ thuật cụ thể có thể gồm FDR, Holm, White’s Reality Check, Deflated Sharpe/performance statistic hoặc bootstrap null; lựa chọn phải được pre-register trong protocol của từng study.

---

## QG-09 — FIRST_ELIGIBLE_PLAN Replay Invariant

Mỗi replay phải khóa tại thời điểm evaluation đầu tiên đủ điều kiện:

```text
first_eligible_evaluation_id
first_eligible_timestamp
first_eligible_trade_plan
available_features_at_that_time
decision_engine_checksum
policy_scope_id
market_data_cutoff
```

Cấm dùng:

- candle chưa đóng tại thời điểm đó;
- outcome, MFE, MAE hoặc giá tương lai làm input;
- TradePlan sinh sau first eligibility;
- regime label hồi tố có sử dụng tương lai;
- entry đẹp hơn được chọn sau khi biết diễn biến.

Replay phải tách:

1. **Policy Replay:** candidate có cho phép/loại quyết định từ snapshot lúc đó hay không.
2. **Outcome Evaluation:** chỉ nối outcome sau khi policy replay đã chốt.

Violation phải trả về `INVALID_REPLAY`, không chỉ warning.

---

## QG-10 — Constrained Pareto / Lexicographic Objective

Cấm tối ưu Win Rate đơn lẻ.

### Stage 1 — Hard constraints

Candidate phải PASS các constraint đã pre-register, ví dụ:

- minimum resolved WIN/LOSS;
- minimum effective_n;
- minimum trades per fold;
- minimum cohort/regime coverage;
- maximum drawdown/tail loss;
- maximum concentration;
- minimum trade retention ratio;
- no unsafe divergence;
- calibration/stability floor khi áp dụng.

Fail một constraint thì loại.

### Stage 2 — Pareto frontier

Chỉ so sánh các candidate không bị candidate khác thống trị trên tập metric đã governance duyệt.

### Stage 3 — Lexicographic tie-break

Thứ tự mặc định:

```text
1. expectancy_R
2. profit_factor
3. shared_stability_score
4. lower complexity / smaller parameter displacement
```

Không dùng tổng trọng số tùy ý.

Nếu một protocol đặc biệt cần weighted score:

- trọng số phải được governance duyệt;
- đóng băng trước khi xem candidate result của vòng đó;
- ghi trong sealed study manifest;
- không được thay đổi hậu nghiệm để “mua” kết quả đẹp.

Mọi báo cáo phải hiển thị baseline trade count, candidate trade count và trade retention ratio để phát hiện nghiệm suy biến “né gần hết giao dịch”.

---

## QG-11 — Explainability và Counterfactual Uncertainty

Không được diễn giải ablation hoặc feature attribution như bằng chứng nhân quả.

Phải phân biệt:

1. **Decision trace:** rule/evidence thật đã được Decision Engine sử dụng.
2. **Feature attribution:** ước lượng phụ thuộc mô hình nghiên cứu.
3. **Historical ablation evidence:** thay đổi hiệu suất khi bỏ feature/group trên replay hợp lệ.

Tên trạng thái được phép:

```text
UNOBSERVABLE
INCONCLUSIVE
ASSOCIATED
ROBUST_ASSOCIATION
```

Không dùng `CAUSAL` nếu không có thiết kế can thiệp nhân quả phù hợp.

Mọi báo cáo phải kèm:

- raw_n, effective_n;
- point estimate;
- uncertainty interval;
- fold/regime coverage;
- model/protocol version;
- cảnh báo giới hạn suy luận.

---

## QG-12 — Cross-Symbol và Temporal Dependence

Dataset phải hỗ trợ ít nhất:

```text
market_event_cluster_id
btc_regime_id
time_bucket
correlation_cluster
symbol_cluster
```

Thống kê/CI phải dùng cluster-aware hoặc block-aware method khi phù hợp.

Một BTC impulse kéo nhiều altcoin không được đếm như nhiều bằng chứng độc lập hoàn toàn.

---

## QG-13 — Scoped Policy Identity

Không được coi mọi thay đổi trong toàn bộ `config.json` là một policy mới theo cách làm vỡ vụn dữ liệu không cần thiết.

Mỗi study/candidate phải có:

```text
decision_engine_checksum
policy_scope_id
policy_scope_hash
policy_scope_schema_version
```

`policy_scope_hash` chỉ bao gồm:

- tham số đang tối ưu;
- các tham số có khả năng tương tác khoa học với tham số đó;
- rule/gate/feature semantics liên quan;
- Decision Engine checksum.

Không mặc định đưa các tham số vận hành không ảnh hưởng policy vào hash, ví dụ:

```text
scan_workers
UI settings
logging
watchlist membership
```

trừ khi study chứng minh chúng ảnh hưởng sampling hoặc outcome và governance yêu cầu đưa vào.

Danh sách tham số tương tác/scope mapping phải nằm trong Governance Artifact, ví dụ:

```text
allowed_quantum_parameters.json
```

Optimizer không được tự chọn hoặc tự sửa scope.

Nếu một fold chứa nhiều full `config_version`, báo cáo bắt buộc:

- liệt kê version;
- giải thích vì sao policy scope vẫn tương thích;
- chạy interaction/confounding check;
- tách fold hoặc chặn study nếu không chứng minh được tính tương thích.

---

## QG-14 — Holdout Consumption Reference

Điều khoản này **không tạo định nghĩa holdout thứ hai**.

Toàn bộ lifecycle, fresh holdout và `consumed=true` được quy định duy nhất tại **QG-07**.

Mọi code, test, manifest và audit cho holdout phải tham chiếu QG-07.

---

## QG-15 — Governance Artifact Integrity

`allowed_quantum_parameters.json` là Governance Artifact, không phải config thông thường.

Quantum chỉ được đọc; không được tự sửa.

Mọi thay đổi allow-list/scope/protocol phải có:

- version;
- manifest tự niêm phong;
- SHA-256 cho từng artifact;
- checksum Decision Engine riêng;
- provenance;
- người/role phê duyệt;
- approval record;
- verify độc lập;
- rollback/archive.

Bàn giao Validation → Shadow phải dùng pattern governance bundle đã kiểm chứng:

```text
Quantum Candidate
→ Validation Report
→ Sealed Manifest + SHA-256
→ Independent Verification
→ Shadow Import
→ Human Approval
```

Không dùng shared mutable state hoặc ghi trực tiếp từ optimizer vào Shadow/MAIN.

---

## QG-16 — Cross-Run Attempt Accounting

Multiple-comparison control phải tính cả số lần thử cộng dồn qua toàn bộ lịch sử, không chỉ số candidate trong một run.

Mỗi `policy_scope_id`/study family phải lưu:

```text
attempt_count_lifetime
attempt_count_since_last_material_policy_change
candidate_count_lifetime
holdout_count_consumed
last_attempt_at
attempt_ledger_hash
```

Mỗi optimization run phải append vào immutable attempt ledger và ghi các trường này trong manifest.

Ngưỡng chấp nhận hoặc null calibration phải nghiêm khắc hơn khi số lần thử cộng dồn tăng, theo protocol pre-register. Cơ chế có thể gồm:

- alpha spending / sequential error budget;
- family-wise correction theo study family;
- bootstrap null có tính best-across-runs;
- yêu cầu effect size/stability cao hơn theo attempt tier.

Tối thiểu, trước Human Approval phải hiển thị rõ:

```text
Đây là lần thử tối ưu thứ N đối với policy scope này.
Tổng số candidate đã đánh giá: M.
Số locked holdout đã consumed: H.
```

Không được reset attempt count bằng cách đổi tên study hoặc thay đổi metadata không trọng yếu.

Material policy change được phép mở study family mới phải được governance định nghĩa và phê duyệt; optimizer không tự quyết.

---

# TRẠNG THÁI QUANTUM HIỆN TẠI

Theo audit dữ liệu được nêu trong phiên thiết kế:

```text
Paper episodes: 236
PENDING: 236
Resolved WIN/LOSS: 0
Effective sample size: 0
```

Trạng thái bắt buộc:

```text
QUANTUM_READINESS = UNOBSERVABLE
OPTIMIZER = LOCKED
RECOMMENDATIONS = LOCKED
APPLY_TO_SHADOW = LOCKED
```

Quantum hiện chỉ được:

- kiểm tra integrity và lineage;
- hiển thị coverage/readiness;
- thống kê PENDING/AMBIGUOUS/EXPIRED_UNFILLED;
- chuẩn bị schema và Dataset Factory;
- báo số mẫu còn thiếu.

Không được sinh threshold recommendation hoặc tuyên bố tìm ra quy luật.

---

# THỨ TỰ TRIỂN KHAI ĐÃ ĐÓNG BĂNG

```text
1. Scientific Safety Addendum
2. Quantum Dataset Factory & Readiness Gate
3. Leakage / FIRST_ELIGIBLE_PLAN replay tests
4. Walk-forward + purge/embargo + ESS framework
5. Governance artifact + attempt ledger
6. Explainability / historical ablation with uncertainty
7. Optimizer
8. Validation → sealed bundle → SHADOW
```

**Không viết Genetic Algorithm/optimizer trước khi các mục 1–5 hoàn thành và audit PASS.**

---

# CHECKLIST AUDIT BẮT BUỘC

Một implementation Quantum chỉ được coi là phù hợp khi auditor xác nhận:

- [ ] QG-01 integrity gate không bypass.
- [ ] QG-02 chỉ WIN/LOSS làm resolved optimization labels.
- [ ] AMBIGUOUS bị loại tường minh khỏi optimizer.
- [ ] QG-03 readiness theo cohort.
- [ ] QG-04 readiness/CI dùng effective_n.
- [ ] QG-05 không random split.
- [ ] QG-06 purge/embargo có test.
- [ ] QG-07 holdout chỉ mở một lần và archived sau consumed.
- [ ] QG-08 multiple testing trong run được kiểm soát.
- [ ] QG-09 replay tôn trọng FIRST_ELIGIBLE_PLAN.
- [ ] QG-10 objective dùng hard constraints + Pareto/lexicographic.
- [ ] QG-11 không tuyên bố nhân quả giả.
- [ ] QG-12 có cluster/block dependence handling.
- [ ] QG-13 policy identity dùng governed scoped hash.
- [ ] QG-14 chỉ tham chiếu QG-07, không định nghĩa trùng.
- [ ] QG-15 artifact được niêm phong và verify độc lập.
- [ ] QG-16 attempt count cộng dồn không thể reset tùy ý.
- [ ] Decision Engine checksum không đổi.
- [ ] Quantum không có execution authority.
- [ ] MAIN không tự động bị sửa.

---

## Quyết định cuối

Bộ **QG-01 → QG-16** là các nguyên tắc/bất biến chính thức đã ĐÓNG BĂNG cho Quantum Lab.

Mọi code, test, UI, report, dataset, optimizer, validation protocol và governance workflow của Quantum phải truy nguyên được về các điều khoản này.
