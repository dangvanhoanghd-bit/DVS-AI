from pathlib import Path
import re

ROOT = Path(__file__).parents[1]


def test_no_non_ascii_text_inside_production_strftime_formats():
    offenders = []
    for path in (ROOT / "dvs_ai").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for match in re.finditer(r"strftime\(([^)]*)\)", source):
            argument = match.group(1)
            if any(ord(char) > 127 for char in argument):
                offenders.append(
                    f"{path.relative_to(ROOT)}: {argument}"
                )
    assert offenders == []


def test_completion_label_formats_time_separately():
    source = (
        ROOT / "dvs_ai/ui/main_window.py"
    ).read_text(encoding="utf-8")
    assert (
        'f"Hoàn tất {datetime.now().strftime(\'%H:%M:%S\')}"'
        in source
    )
    assert (
        'strftime("Hoàn tất %H:%M:%S")'
        not in source
    )
