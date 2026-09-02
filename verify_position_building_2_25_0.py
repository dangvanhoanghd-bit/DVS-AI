from pathlib import Path
import json

root = Path(__file__).resolve().parent
engine = (root / "dvs_ai/engines/microstructure/position_building_engine.py").read_text(encoding="utf-8")
scanner = (root / "dvs_ai/services/scanner.py").read_text(encoding="utf-8")
worker = (root / "dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
manifest = json.loads((root / "POSITION_BUILDING_TRUTH_MANIFEST.json").read_text(encoding="utf-8"))
checks = {
    "version": "2.25.0-alpha" in (root / "dvs_ai/__init__.py").read_text(encoding="utf-8"),
    "normalization": '"input_normalization": "FAIL_SAFE_V3"' in engine,
    "refresh_method": "def refresh_position_footprint" in scanner,
    "finalization_order": worker.index("hydrate_microstructure(") < worker.index("refresh_position_footprint(ranked)") < worker.index("apply_microstructure_adjustments("),
    "truth_manifest": manifest.get("status") == "TRUTH_VERIFIED_WITH_LIMITATIONS",
    "live_disabled": manifest["safety"]["live_execution_enabled"] is False,
}
failed = [name for name, ok in checks.items() if not ok]
if failed:
    raise SystemExit("FAIL: " + ", ".join(failed))
print("DVS AI Alpha 2.25.0 Position Building truth verifier: PASS")
