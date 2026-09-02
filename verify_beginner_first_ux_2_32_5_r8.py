from pathlib import Path

root = Path(__file__).resolve().parent
ui = (root / "dvs_ai/ui/main_window.py").read_text(encoding="utf-8")
presenter = (root / "dvs_ai/services/plain_language_presenter.py").read_text(encoding="utf-8")
required = [
    "Chế độ: Dễ hiểu", "Chế độ: Chuyên gia", "AI Coach:",
    "Vì sao?", "Cần chờ gì?", "PlainLanguagePresenter",
]
missing = [x for x in required if x not in ui and x not in presenter]
for forbidden in ("send_order", "place_order", "promote_main", "apply_shadow"):
    if forbidden in presenter.lower():
        raise SystemExit(f"FAIL: presenter contains forbidden dependency {forbidden}")
if missing:
    raise SystemExit(f"FAIL: missing {missing}")
print("PASS: Beginner-first UX source isolation and required UX elements")
