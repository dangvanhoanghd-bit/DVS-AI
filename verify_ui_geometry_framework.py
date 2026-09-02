from pathlib import Path
import py_compile

main = Path("main_window.py")
manager = Path("ui_geometry_manager.py")

py_compile.compile(str(main), doraise=True)
py_compile.compile(str(manager), doraise=True)

main_source = main.read_text(encoding="utf-8")
manager_source = manager.read_text(encoding="utf-8")

assert "UIGeometryManager" in main_source
assert "self.ui_geometry.capture_view_state()" in main_source
assert "self.ui_geometry.schedule_view_restore(snapshot)" in main_source
assert "self.ui_geometry.observe_resize(" in main_source

assert "class UIGeometryManager" in manager_source
assert "class LayoutFreezeContext" in manager_source
assert "class WindowGeometrySnapshot" in manager_source

resize_start = main_source.index("def resizeEvent")
resize_end = main_source.index("def closeEvent", resize_start)
resize_body = main_source[resize_start:resize_end]
assert "self.resize(" not in resize_body
assert "self.setGeometry(" not in resize_body
assert "self.adjustSize(" not in resize_body

restore_start = manager_source.index("def restore_view_state")
restore_end = manager_source.index("def schedule_view_restore", restore_start)
restore_body = manager_source[restore_start:restore_end]
assert "resize(" not in restore_body
assert "setGeometry(" not in restore_body
assert "adjustSize(" not in restore_body

print("UI Geometry Framework verification: PASS")
