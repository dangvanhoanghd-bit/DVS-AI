# Beta 4A — Burn-in Evidence Collector

Trong lúc DVS AI đang chạy, nhấp đúp `COLLECT_BETA4A_BURNIN_2H.bat`.

Collector ghi một snapshot mỗi 60 giây trong 2 giờ và tạo một gói ZIP tại:

`artifacts/beta4a_burnin/BETA4A_BURNIN_EVIDENCE_<timestamp>.zip`

Gói bằng chứng gồm:

- chuỗi thời gian RSS/CPU/số thread/open files nếu máy có `psutil`;
- số dòng từng bảng SQLite theo từng snapshot;
- `PRAGMA quick_check`;
- bản sao cơ sở dữ liệu ở cuối phiên;
- phần cuối của `dvs_ai.log`;
- manifest SHA-256.

Không cần dừng DVS AI. Collector chỉ mở SQLite ở chế độ read-only.

Nếu `psutil` chưa được cài, collector vẫn thu thập database và log. Để có thêm số liệu tiến trình:

`python -m pip install psutil`

Có thể chạy thử nhanh 2 phút:

`python beta4a_burnin_collector.py --duration-minutes 2 --interval-seconds 15`
