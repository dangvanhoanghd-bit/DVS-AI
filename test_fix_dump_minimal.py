from __future__ import annotations

import json
from pathlib import Path

from beta4a_burnin_collector import collect_current_session_freeze_evidence


def test_collector_accepts_only_current_session(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    session_id = "session_test"
    session_dir = runtime / "freeze_dumps" / session_id
    session_dir.mkdir(parents=True)
    dump = session_dir / "freeze_dump.log"
    meta = session_dir / "freeze_dump_metadata.json"
    header = {"session_id": session_id, "pid": 123}
    dump.write_text("DVS_FREEZE_DUMP_HEADER " + json.dumps(header, sort_keys=True) + "\n", encoding="utf-8")
    meta.write_text(json.dumps(header), encoding="utf-8")
    (runtime / "runtime_status.json").write_text(
        json.dumps({
            "session_id": session_id,
            "pid": 123,
            "freeze_dump_path": str(dump.resolve()),
            "freeze_dump_metadata_path": str(meta.resolve()),
        }),
        encoding="utf-8",
    )
    out = tmp_path / "out"
    result = collect_current_session_freeze_evidence(runtime, out)
    assert result["status"] == "VALID_CURRENT_SESSION"
    assert (out / "freeze_dump.log").is_file()
    assert (out / "freeze_dump_metadata.json").is_file()
