from pathlib import Path

from dvs_ai.version import APP_VERSION


def test_release_identity_has_single_dynamic_source_of_truth():
    launcher = Path("START_DVS_AI.bat").read_text(encoding="utf-8")
    assert APP_VERSION
    assert APP_VERSION in launcher


def test_current_release_tests_do_not_assert_retired_version_literal():
    forbidden_assertion = "assert 'APP_VERSION = \"4.3.0E-3-QI-3\"'"
    for path in Path("tests").glob("test_*.py"):
        if path.resolve() == Path(__file__).resolve():
            continue
        assert forbidden_assertion not in path.read_text(encoding="utf-8", errors="ignore")
