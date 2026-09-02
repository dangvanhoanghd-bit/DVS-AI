from pathlib import Path
import re

ROOT = Path(__file__).parents[1]


def test_no_invalid_annotations_import_anywhere():
    offenders = []
    for path in ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if re.search(
            r"^\s*import\s+annotations\s*$",
            source,
            re.MULTILINE,
        ):
            offenders.append(str(path.relative_to(ROOT)))
        if re.search(
            r"^\s*from\s+annotations\s+import\b",
            source,
            re.MULTILINE,
        ):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_main_window_starts_with_future_annotations():
    source = (
        ROOT / "dvs_ai/ui/main_window.py"
    ).read_text(encoding="utf-8")
    assert source.startswith("from __future__ import annotations")
