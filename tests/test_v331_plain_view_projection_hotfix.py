from pathlib import Path


def test_plain_view_built_before_core_summary_render():
    source = (Path(__file__).parents[1] / "dvs_ai" / "ui" / "main_window.py").read_text(encoding="utf-8")
    start = source.index("def _show_selected_impl")
    build = source.index("plain_view = self.plain_language_presenter.build(a)", start)
    render = source.index("self.core_summary.setHtml(self._plain_view_html(plain_view", build)
    assert build < render
