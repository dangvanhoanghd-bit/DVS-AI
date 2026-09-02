from pathlib import Path

root = Path(__file__).resolve().parent
truth = (root / 'dvs_ai/ui/truth_dashboard.py').read_text(encoding='utf-8')
main = (root / 'dvs_ai/ui/main_window.py').read_text(encoding='utf-8')
checks = {
    'scroll_container': 'QScrollArea' in truth and 'setWidgetResizable(True)' in truth,
    'card_min_height': 'self.setMinimumHeight(108)' in truth,
    'chart_min_height': 'self.setMinimumHeight(230)' in truth,
    'responsive_reflow': 'def _reflow_cards' in truth and 'width < 1050' in truth and 'width < 1500' in truth,
    'history_throttle': 'HISTORY_REFRESH_SECONDS = 10.0' in truth,
    'ai_health': '_TruthCard("AI Health")' in truth,
    'next_action': '_TruthCard("Next Action")' in truth,
    'historical_integrity': 'Historical Evidence Integrity' in truth,
    'version': 'APP_VERSION = "2.30.0"' in main,
    'edition': 'APP_EDITION = "Commercial Truth Dashboard V3"' in main,
    'observe_only': not any(x in truth.lower() for x in ('send_order','tradeintent','positionsizer','promote_to_main','apply_shadow')),
}
failed = [name for name, ok in checks.items() if not ok]
for name, ok in checks.items():
    print(f'{name}: {"PASS" if ok else "FAIL"}')
if failed:
    raise SystemExit('Verifier failed: ' + ', '.join(failed))
print('Truth Dashboard V3 verifier: PASS')
