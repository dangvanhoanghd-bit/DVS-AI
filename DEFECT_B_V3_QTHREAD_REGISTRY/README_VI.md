# Defect B Production Patch v3 — QThread Lifecycle Registry

Bản này cài registry trước khi các module UI DVS AI được import, nên mọi QThread được tạo qua `PySide6.QtCore.QThread` sau thời điểm đó sẽ tự đăng ký.

Telemetry mới: `artifacts/runtime/qthread_lifecycle.jsonl`.

Khi đóng ứng dụng:
1. dump registry ngay khi vào closeEvent;
2. chạy các shutdown hook hiện có;
3. yêu cầu interruption/quit cho mọi QThread còn đăng ký;
4. chờ hữu hạn 5000 ms;
5. nếu còn survivor, từ chối đóng và ghi `qthread_registry_shutdown_timeout`.

Giới hạn minh bạch: registry không thể bảo đảm bắt các native thread/QThread được thư viện bên thứ ba tạo bằng binding đã cache trước khi hook được cài, hoặc thread không đi qua `PySide6.QtCore.QThread`. QObject-tree/console evidence vẫn cần dùng bổ sung.
