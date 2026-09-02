from pathlib import Path

root = Path(__file__).resolve().parent
main = (root / 'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
overlay = (root / 'dvs_ai/ui/performance_overlay.py').read_text(encoding='utf-8')
profiler = (root / 'dvs_ai/ui/ui_performance_profiler.py').read_text(encoding='utf-8')

checks = {
    'version_2_24_3': 'APP_VERSION = "2.24.3"' in main,
    'real_overlay_module': 'class PerformanceOverlay(QFrame)' in overlay,
    'scheduler_metrics': 'scheduler_provider' in overlay and 'last_frame_ms' in overlay,
    'cell_diff_metrics': 'table_provider' in overlay and 'cells_changed' in overlay,
    'event_loop_metrics': 'last_event_loop_lag_ms' in profiler and 'max_event_loop_lag_ms' in profiler,
    'worker_state': 'worker_provider' in overlay and '_performance_worker_state' in main,
    'live_timer': 'self._timer.timeout.connect(self.refresh_metrics)' in overlay,
    'toggle_shortcut': '("Ctrl+Shift+P", self.toggle_performance_overlay)' in main,
    'session_persistence': 'commercial/performance_overlay' in main,
    'lifecycle_close': 'self.performance_overlay.close_overlay()' in main,
    'resize_reposition': 'self.performance_overlay.reposition()' in main,
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(('PASS' if ok else 'FAIL'), name)
if failed:
    raise SystemExit('Release verifier failed: ' + ', '.join(failed))
print('DVS AI Alpha 2.24.3 release verifier: PASS')
