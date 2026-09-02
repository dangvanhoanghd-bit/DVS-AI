# Defect B Production Patch v4

Bản vá thêm cooperative cancellation và deadline hữu hạn cho OutcomeResolutionCoordinator và ba stage nội bộ: scan signals, paper trades, candidate outcomes.

Telemetry: `artifacts/runtime/outcome_resolution_lifecycle.jsonl`.

PASS runtime yêu cầu `outcome_resolution_shutdown_requested` dẫn tới `outcome_resolution_shutdown_completed` trong <= 5000 ms, không có QThread fatal và process thoát sạch.
