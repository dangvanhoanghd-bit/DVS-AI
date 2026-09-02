from __future__ import annotations

import hashlib
import html
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .report_models import EvidenceAnalysisResult


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _jsonable(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, tuple):
        return [_jsonable(v) for v in value]
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if hasattr(value, "__dataclass_fields__"):
        return {k: _jsonable(v) for k, v in asdict(value).items()}
    return value


@dataclass(frozen=True)
class ExecutiveReportArtifact:
    schema: str
    protocol_version: str
    context_id: str
    generated_at: str
    source_result_hash: str
    sections: tuple[tuple[str, Any], ...]
    artifact_hash: str

    def payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "protocol_version": self.protocol_version,
            "context_id": self.context_id,
            "generated_at": self.generated_at,
            "source_result_hash": self.source_result_hash,
            "sections": {k: _jsonable(v) for k, v in self.sections},
        }

    def verify(self) -> bool:
        return self.artifact_hash == hashlib.sha256(_canonical(self.payload()).encode()).hexdigest()


class ExecutiveReportGenerator:
    SCHEMA = "DVS_EVIDENCE_EXECUTIVE_REPORT_V1"

    @staticmethod
    def build(result: EvidenceAnalysisResult, *, generated_at: str | None = None) -> ExecutiveReportArtifact:
        raw = _jsonable(result)
        source_hash = hashlib.sha256(_canonical(raw).encode()).hexdigest()
        sections = (
            ("executive_summary", {
                "recommendation": result.recommendation.recommendation,
                "recommendation_state": result.recommendation.state,
                "confidence": result.confidence.confidence_level,
                "conclusion": result.confidence.conclusion_state,
                "integrity": result.integrity.state,
            }),
            ("integrity_report", result.integrity),
            ("evidence_report", result.evidence),
            ("confidence_report", result.confidence),
            ("actionable_gap_report", result.gap),
            ("recommendation", result.recommendation),
        )
        timestamp = generated_at or datetime.now(timezone.utc).isoformat()
        unsigned = {
            "schema": ExecutiveReportGenerator.SCHEMA,
            "protocol_version": result.protocol_version,
            "context_id": result.context_id,
            "generated_at": timestamp,
            "source_result_hash": source_hash,
            "sections": {k: _jsonable(v) for k, v in sections},
        }
        digest = hashlib.sha256(_canonical(unsigned).encode()).hexdigest()
        return ExecutiveReportArtifact(
            ExecutiveReportGenerator.SCHEMA, result.protocol_version, result.context_id,
            timestamp, source_hash, sections, digest,
        )

    @staticmethod
    def to_json(report: ExecutiveReportArtifact) -> str:
        if not report.verify():
            raise ValueError("REPORT_ARTIFACT_INVALID")
        return json.dumps({**report.payload(), "artifact_hash": report.artifact_hash}, ensure_ascii=False, indent=2)

    @staticmethod
    def to_markdown(report: ExecutiveReportArtifact) -> str:
        if not report.verify():
            raise ValueError("REPORT_ARTIFACT_INVALID")
        sections = report.payload()["sections"]
        summary = sections["executive_summary"]
        lines = [
            "# DVS AI Evidence Analysis Report", "",
            f"- Context: `{report.context_id}`", f"- Protocol: `{report.protocol_version}`",
            f"- Recommendation: **{summary['recommendation']}**",
            f"- Conclusion: **{summary['conclusion']}**", f"- Confidence: **{summary['confidence']}**", "",
        ]
        for title, payload in sections.items():
            lines += [f"## {title.replace('_',' ').title()}", "", "```json", json.dumps(payload, ensure_ascii=False, indent=2), "```", ""]
        lines += [f"Artifact SHA-256: `{report.artifact_hash}`"]
        return "\n".join(lines)

    @staticmethod
    def to_html(report: ExecutiveReportArtifact) -> str:
        md = ExecutiveReportGenerator.to_markdown(report)
        return "<!doctype html><html><meta charset='utf-8'><title>DVS Evidence Report</title><body><pre>" + html.escape(md) + "</pre></body></html>"


class EvidenceReportStore:
    """Append-only report persistence. Existing artifact files are never overwritten."""
    def __init__(self, root: str | Path = "data/evidence_reports"):
        self.root = Path(root)

    def persist(self, report: ExecutiveReportArtifact) -> dict[str, str]:
        if not report.verify():
            raise ValueError("REPORT_ARTIFACT_INVALID")
        self.root.mkdir(parents=True, exist_ok=True)
        stem = f"{report.context_id}_{report.artifact_hash[:16]}"
        paths = {
            "json": self.root / f"{stem}.json",
            "md": self.root / f"{stem}.md",
            "html": self.root / f"{stem}.html",
        }
        content = {
            "json": ExecutiveReportGenerator.to_json(report),
            "md": ExecutiveReportGenerator.to_markdown(report),
            "html": ExecutiveReportGenerator.to_html(report),
        }
        for kind, path in paths.items():
            if path.exists():
                if path.read_text(encoding="utf-8") != content[kind]:
                    raise FileExistsError("APPEND_ONLY_REPORT_COLLISION")
                continue
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(content[kind], encoding="utf-8")
            tmp.replace(path)
        return {k: str(v) for k, v in paths.items()}
