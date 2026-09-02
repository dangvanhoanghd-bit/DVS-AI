# DVS AI Alpha 4.2.0-UI-r2
## Compact Folder Navigation & Startup Lifecycle Fix

Baseline: 4.2.0-UI-r1.

### Primary navigation
The main tab bar is reduced to seven operator-oriented entries:
1. Dashboard
2. Phân tích chi tiết
3. Giao dịch
4. Phân tích thị trường
5. Giám sát
6. Nghiên cứu
7. Công cụ

### Folder contents
- Giao dịch: Decision Core, Smart Entry, Paper Trade.
- Phân tích thị trường: Learning, Liquidity & Wyckoff, Smart Money, Quantum Optimizer, Lịch sử tín hiệu, Truth Dashboard.
- Giám sát: Statistical Diagnostics, Episode Integrity, Integrity History, Integrity Alerts, Integrity Operations, Episode Audit.
- Nghiên cứu: Thí nghiệm, So sánh & tái lập, Cohort & Batch.
- Công cụ: Trung tâm lỗi.

### Startup fix
QApplication is now created before QObject/QThread/QEventLoop-backed runtimes. This removes the Windows startup warning:
`QEventLoop: Cannot be used without QCoreApplication`.

### Scientific boundary
Presentation and startup lifecycle only. No Decision Engine, score, threshold, gate, trading, canonical-data, research-result, or integrity-policy changes.

### Verification
- 742 tests passed.
- compileall passed.
- 27 engine Python files unchanged against 4.2.0-UI-r1.
- Decision Engine MD5: 72cf7d54e1ed6369400683358da8c0ef.
