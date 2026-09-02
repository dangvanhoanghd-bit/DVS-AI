"""Real PySide6 startup smoke test for Windows/release validation."""
from __future__ import annotations

import os
import sys
import traceback

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def main() -> int:
    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QApplication
        from dvs_ai.config import load_config
        from dvs_ai.data.binance_provider import BinanceFuturesProvider
        from dvs_ai.engines.indicator_engine import IndicatorEngine
        from dvs_ai.engines.decision_engine import DecisionEngine
        from dvs_ai.services.scanner import ScannerService
        from dvs_ai.services.signal_recorder import SignalRecorder
        from dvs_ai.services.history_service import HistoryService
        from dvs_ai.services.outcome_tracker import OutcomeTracker
        from dvs_ai.services.paper_trade_service import PaperTradeService
        from dvs_ai.services.learning_service import LearningService
        from dvs_ai.ui.main_window import MainWindow

        config = load_config()
        provider = BinanceFuturesProvider()
        decision = DecisionEngine(config)
        service = ScannerService(provider, IndicatorEngine(), decision, config.ohlcv_limit)
        app = QApplication.instance() or QApplication([])
        window = MainWindow(
            config,
            service,
            SignalRecorder(),
            HistoryService(),
            OutcomeTracker(provider),
            PaperTradeService(provider, decision, config=config),
            LearningService(),
        )
        window.show()
        QTimer.singleShot(1500, app.quit)
        code = app.exec()
        print("STARTUP_SMOKE_PASS: MainWindow created and event loop ran.")
        return int(code)
    except Exception:
        traceback.print_exc()
        print("STARTUP_SMOKE_FAIL")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
