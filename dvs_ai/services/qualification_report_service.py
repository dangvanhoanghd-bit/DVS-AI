from __future__ import annotations

"""Read-only scientific qualification report generation.

The service consumes the append-only shadow agreement store and emits audit
artifacts only.  It has no execution, promotion, or authority-switch API.
"""

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
from typing import Iterable

from dvs_ai.services.core_shadow_agreement_service import (
    CoreShadowAgreementStore,
    FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE,
    QualificationBreakdown,
)


@dataclass(frozen=True, slots=True)
class QualificationReportSnapshot:
    generated_at: str
    build_version: str
    report_title: str
    qualification_status: str
    paper_authority: str
    total_cycles: int
    minimum_cycles: int
    remaining_cycles: int
    full_agreements: int
    partial_agreements: int
    conservative_divergences: int
    unsafe_divergences: int
    full_agreement_ratio: float
    required_full_agreement_ratio: float
    actionable_cycles: int
    actionable_ratio: float
    required_actionable_cycles: int
    actionable_gap: int
    decision_agreement_confidence: float | None
    evidence_observability: str
    profile_id: str
    profile_hash: str
    integrity_pass: int
    integrity_failed: int
    legacy_unsealed: int
    by_symbol: tuple[QualificationBreakdown, ...]
    by_regime: tuple[QualificationBreakdown, ...]
    by_phase: tuple[QualificationBreakdown, ...]
    by_confidence_bucket: tuple[QualificationBreakdown, ...]
    unsafe_cases: tuple[tuple[str, str, str, str], ...]
    governance_recommendation: str


class QualificationReportService:
    """Generate deterministic, read-only scientific qualification artifacts."""

    def __init__(self, store: CoreShadowAgreementStore, *, build_version: str) -> None:
        self._store = store
        self._build_version = str(build_version)

    def build_snapshot(self) -> QualificationReportSnapshot:
        metrics = self._store.metrics(FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE)
        analytics = self._store.analytics(FROZEN_PAPER_AUTHORITY_HANDOVER_PROFILE)
        evidence = self._store.list_evidence(limit=100000)
        integrity_pass = sum(1 for row in evidence if row.integrity_status == "PASS")
        integrity_failed = sum(1 for row in evidence if row.integrity_status == "FAILED")
        legacy_unsealed = sum(1 for row in evidence if row.integrity_status == "LEGACY_UNSEALED")
        recommendation = (
            "READY_FOR_GOVERNANCE_REVIEW"
            if metrics.qualification_status == "READY_FOR_GOVERNANCE_REVIEW" and integrity_failed == 0
            else "NOT_READY"
        )
        return QualificationReportSnapshot(
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            build_version=self._build_version,
            report_title="DVS AI Scientific Qualification Report",
            qualification_status=metrics.qualification_status,
            paper_authority="LEGACY",
            total_cycles=metrics.total_cycles,
            minimum_cycles=metrics.minimum_cycles,
            remaining_cycles=max(0, metrics.minimum_cycles - metrics.total_cycles),
            full_agreements=metrics.full_agreements,
            partial_agreements=metrics.partial_agreements,
            conservative_divergences=metrics.conservative_divergences,
            unsafe_divergences=metrics.unsafe_divergences,
            full_agreement_ratio=metrics.full_agreement_ratio,
            required_full_agreement_ratio=metrics.required_full_agreement_ratio,
            actionable_cycles=metrics.actionable_cycles,
            actionable_ratio=metrics.actionable_ratio,
            required_actionable_cycles=metrics.required_actionable_cycles,
            actionable_gap=metrics.actionable_gap,
            decision_agreement_confidence=metrics.decision_agreement_confidence,
            evidence_observability=("OBSERVABLE" if metrics.actionable_cycles else "UNOBSERVABLE"),
            profile_id=metrics.profile_id,
            profile_hash=metrics.profile_hash,
            integrity_pass=integrity_pass,
            integrity_failed=integrity_failed,
            legacy_unsealed=legacy_unsealed,
            by_symbol=analytics.by_symbol,
            by_regime=analytics.by_regime,
            by_phase=analytics.by_phase,
            by_confidence_bucket=analytics.by_confidence_bucket,
            unsafe_cases=analytics.unsafe_cases,
            governance_recommendation=recommendation,
        )

    @staticmethod
    def _payload(snapshot: QualificationReportSnapshot) -> dict[str, object]:
        payload = asdict(snapshot)
        payload["known_limitations"] = {
            "cross_symbol_dependence": "Episode-level analysis removes repeated observations within the same symbol/setup, but different symbols are still treated as separate observations. Shared BTC shocks, market-wide moves, and sector correlation are not yet controlled; effective independent sample size may be lower than the observed episode count."
        }
        payload["safety_boundary"] = {
            "unified_mode": "SHADOW_ONLY",
            "paper_authority": "LEGACY",
            "automatic_promotion": False,
            "exchange_order_capability": False,
        }
        return payload

    def export_json(self, destination: str | Path) -> Path:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._payload(self.build_snapshot()), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @staticmethod
    def _breakdown_rows(items: Iterable[QualificationBreakdown]) -> str:
        rows = []
        for item in items:
            rows.append(
                "<tr>"
                f"<td>{escape(item.key)}</td><td>{item.total}</td><td>{item.full}</td>"
                f"<td>{item.partial}</td><td>{item.conservative}</td><td>{item.unsafe}</td>"
                f"<td>{item.full_ratio * 100:.2f}%</td></tr>"
            )
        return "".join(rows) or '<tr><td colspan="7">No observations</td></tr>'

    def render_html(self) -> str:
        s = self.build_snapshot()
        table_head = "<tr><th>Key</th><th>Total</th><th>Full</th><th>Partial</th><th>Conservative</th><th>Unsafe</th><th>Full %</th></tr>"
        return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>{escape(s.report_title)}</title>
<style>
body{{font-family:Arial,sans-serif;margin:32px;color:#17202a}}h1,h2{{color:#123a63}}
.cards{{display:flex;gap:12px;flex-wrap:wrap}}.card{{border:1px solid #ccd6e0;border-radius:8px;padding:12px;min-width:150px}}
table{{border-collapse:collapse;width:100%;margin:12px 0 24px}}th,td{{border:1px solid #ccd6e0;padding:7px;text-align:left}}th{{background:#eef4f8}}
.safe{{padding:12px;background:#eef8f0;border-left:4px solid #2d7d46}}.warn{{padding:12px;background:#fff7e6;border-left:4px solid #aa6d00}}
code{{word-break:break-all}}</style></head><body>
<h1>{escape(s.report_title)}</h1>
<p>Build {escape(s.build_version)} · Generated {escape(s.generated_at)}</p>
<div class="{'safe' if s.governance_recommendation == 'READY_FOR_GOVERNANCE_REVIEW' else 'warn'}"><b>Recommendation:</b> {escape(s.governance_recommendation)}<br>
This report never transfers authority. Paper Authority remains LEGACY.</div>
<h2>Executive Summary</h2><div class="cards">
<div class="card"><b>Status</b><br>{escape(s.qualification_status)}</div>
<div class="card"><b>Cycles</b><br>{s.total_cycles} / {s.minimum_cycles}</div>
<div class="card"><b>Full Agreement</b><br>{s.full_agreement_ratio*100:.2f}% / {s.required_full_agreement_ratio*100:.2f}%</div>
<div class="card"><b>Unsafe</b><br>{s.unsafe_divergences}</div>
<div class="card"><b>Actionable</b><br>{s.actionable_cycles}/{s.required_actionable_cycles} ({s.actionable_ratio*100:.2f}%)</div>
<div class="card"><b>Observability</b><br>{escape(s.evidence_observability)}</div>
<div class="card"><b>Remaining</b><br>{s.remaining_cycles}</div></div>
<h2>Integrity Summary</h2><p>PASS: {s.integrity_pass} · FAILED: {s.integrity_failed} · LEGACY_UNSEALED: {s.legacy_unsealed}</p>
<h2>By Symbol</h2><table>{table_head}{self._breakdown_rows(s.by_symbol)}</table>
<h2>By Regime</h2><table>{table_head}{self._breakdown_rows(s.by_regime)}</table>
<h2>By Phase</h2><table>{table_head}{self._breakdown_rows(s.by_phase)}</table>
<h2>By Confidence Bucket</h2><table>{table_head}{self._breakdown_rows(s.by_confidence_bucket)}</table>
<h2>Governance Profile</h2><p>ID: {escape(s.profile_id)}<br>Hash: <code>{escape(s.profile_hash)}</code></p>
<h2>Known Statistical Limitations</h2><div class="warn"><b>Cross-Symbol Dependence:</b> Episode-level analysis removes repeated observations within the same symbol and setup episode. Outcomes across different symbols are currently treated as separate observations. Shared BTC shocks, broad market moves, and sector correlation are not yet controlled; effective independent sample size may be lower than the observed episode count.</div>
<h2>Safety Boundary</h2><ul><li>Unified Core: SHADOW_ONLY</li><li>Paper Authority: LEGACY</li><li>Automatic promotion: disabled</li><li>Exchange order capability: absent</li></ul>
</body></html>"""

    def export_html(self, destination: str | Path) -> Path:
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.render_html(), encoding="utf-8")
        return path

    def export_pdf(self, destination: str | Path) -> Path:
        """Write a dependency-free text PDF suitable for archival review."""
        s = self.build_snapshot()
        lines = [
            s.report_title,
            f"Build: {s.build_version}", f"Generated: {s.generated_at}",
            f"Qualification Status: {s.qualification_status}",
            f"Governance Recommendation: {s.governance_recommendation}",
            f"Cycles: {s.total_cycles}/{s.minimum_cycles} (remaining {s.remaining_cycles})",
            f"Full Agreement: {s.full_agreement_ratio*100:.2f}% / {s.required_full_agreement_ratio*100:.2f}%",
            f"Unsafe Divergences: {s.unsafe_divergences}",
            f"Actionable Evidence: {s.actionable_cycles}/{s.required_actionable_cycles} ({s.actionable_ratio*100:.2f}%)",
            f"Decision Agreement Confidence: {'N/A - UNOBSERVABLE' if s.decision_agreement_confidence is None else f'{s.decision_agreement_confidence*100:.2f}%'}",
            f"Integrity PASS/FAILED/UNSEALED: {s.integrity_pass}/{s.integrity_failed}/{s.legacy_unsealed}",
            "Paper Authority: LEGACY", "Unified Core: SHADOW_ONLY", "", "By Symbol:",
        ]
        lines.extend(f"{x.key}: total={x.total}, full={x.full}, unsafe={x.unsafe}, full%={x.full_ratio*100:.2f}" for x in s.by_symbol[:30])
        lines.extend(["", f"Profile ID: {s.profile_id}", f"Profile Hash: {s.profile_hash}"])
        content_lines = ["BT", "/F1 10 Tf", "50 790 Td"]
        first = True
        for line in lines[:55]:
            safe = str(line).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            if not first:
                content_lines.append("0 -14 Td")
            content_lines.append(f"({safe}) Tj")
            first = False
        content_lines.append("ET")
        stream = "\n".join(content_lines).encode("latin-1", errors="replace")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        ]
        pdf = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for idx, obj in enumerate(objects, 1):
            offsets.append(len(pdf)); pdf.extend(f"{idx} 0 obj\n".encode()); pdf.extend(obj); pdf.extend(b"\nendobj\n")
        xref = len(pdf); pdf.extend(f"xref\n0 {len(objects)+1}\n".encode()); pdf.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]: pdf.extend(f"{offset:010d} 00000 n \n".encode())
        pdf.extend(f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
        path = Path(destination); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(bytes(pdf)); return path
