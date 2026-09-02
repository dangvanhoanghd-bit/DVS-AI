from __future__ import annotations

import math
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable

from .unified_outcome_service import UnifiedOutcomeService


class LearningService:
    # Legacy terminal vocabulary excluded from determinate calibration: 'AMBIGUOUS','PARTIAL_AMBIGUOUS','EXPIRED'
    """
    Read-only analytics over Paper Trading + signal evaluation data.

    This service does not silently change production thresholds or engine
    weights. It produces evidence and recommendations only.
    """

    MIN_SETUP_SAMPLE = 5
    MIN_CALIBRATION_SAMPLE = 8

    def __init__(self, db_path: str = "data/dvs_paper_trades.db", unified_service: UnifiedOutcomeService | None = None) -> None:
        self.db_path = Path(db_path)
        self.unified_service = unified_service or UnifiedOutcomeService(self.db_path)
        self._snapshot_cache = None
        self._snapshot_cache_key = None
        self._snapshot_cached_at = 0.0
        self._retention_replacement_callback = None
        self._cancel_check: Callable[[str], bool] | None = None

    def set_cancel_check(
        self,
        callback: Callable[[str], bool] | None,
    ) -> None:
        self._cancel_check = callback
        setter = getattr(self.unified_service, "set_cancel_check", None)
        if callable(setter):
            setter(callback)

    def _check_cancel(self, stage: str) -> bool:
        callback = self._cancel_check
        if callback is None:
            return False
        try:
            cancelled = bool(callback(stage))
        except Exception:
            cancelled = False
        if cancelled:
            try:
                from dvs_ai.runtime.learning_cooperative_return import (
                    record_cooperative_return,
                )
                record_cooperative_return(
                    "learning_service_cancel_observed",
                    stage=str(stage),
                )
            except Exception:
                pass
        return cancelled

    def _snapshot(self):
        if self._check_cancel("learning_snapshot_enter"):
            return self._snapshot_cache or ([], [])
        try:
            stat = self.db_path.stat()
            key = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            key = None
        now = time.monotonic()
        if self._snapshot_cache is not None and self._snapshot_cache_key == key and now - self._snapshot_cached_at < 5.0:
            return self._snapshot_cache
        if self._check_cancel("learning_records_enter"):
            return self._snapshot_cache or ([], [])
        records = self.unified_service.records()
        if self._check_cancel("learning_records_exit"):
            return self._snapshot_cache or ([], [])
        rows = self.unified_service.learning_ready()
        if self._check_cancel("learning_ready_exit"):
            return self._snapshot_cache or ([], [])
        if not rows and not self.unified_service.pipeline_schema_available():
            rows = self.unified_service.legacy_compat_learning_ready()
        old_cache = self._snapshot_cache
        new_cache = (records, rows)
        self._snapshot_cache = new_cache
        callback = self._retention_replacement_callback
        if callback is not None:
            callback(old_cache, new_cache, "db_snapshot_refresh")
        self._snapshot_cache_key = key
        self._snapshot_cached_at = now
        return self._snapshot_cache

    def invalidate_cache(self) -> None:
        old_cache = self._snapshot_cache
        self._snapshot_cache = None
        callback = self._retention_replacement_callback
        if callback is not None and old_cache is not None:
            callback(old_cache, None, "explicit_invalidate")
        self._snapshot_cache_key = None
        self._snapshot_cached_at = 0.0

    def _learning_rows(self, lab: str | None = None):
        if self._check_cancel("learning_rows_enter"):
            return []
        rows = list(self._snapshot()[1])
        if lab:
            lab = lab.upper()
            rows = [row for row in rows if str(row.cohort or "").upper() == lab]
        return rows

    def _connect(self):
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _safe_pf(gross_win: float, gross_loss: float) -> float:
        if gross_loss > 0:
            return gross_win / gross_loss
        if gross_win > 0:
            return float("inf")
        return 0.0

    def overview(self, lab: str | None = None) -> dict:
        if self._check_cancel(f"overview_enter:{lab or 'ALL'}"):
            return {}
        records = list(self._snapshot()[0])
        if self._check_cancel(f"overview_records_ready:{lab or 'ALL'}"):
            return {}
        rows = self._learning_rows(lab)
        if self._check_cancel(f"overview_rows_ready:{lab or 'ALL'}"):
            return {}
        if lab:
            lab_u = lab.upper()
            records = [r for r in records if str(r.cohort or "").upper() == lab_u]
        wins = sum(r.outcome_status == "WIN" for r in rows)
        losses = sum(r.outcome_status == "LOSS" for r in rows)
        gross_win = sum(float(r.realized_r or 0.0) for r in rows if float(r.realized_r or 0.0) > 0)
        gross_loss = abs(sum(float(r.realized_r or 0.0) for r in rows if float(r.realized_r or 0.0) < 0))
        long_rows = [r for r in rows if str(r.direction).upper() == "LONG"]
        short_rows = [r for r in rows if str(r.direction).upper() == "SHORT"]
        return {
            "total": len(records),
            "closed": len(rows),
            "wins": wins,
            "losses": losses,
            "breakeven": sum(float(r.realized_r or 0.0) == 0 for r in rows),
            "win_rate": wins / len(rows) * 100.0 if rows else 0.0,
            "avg_r": sum(float(r.realized_r or 0.0) for r in rows) / len(rows) if rows else 0.0,
            "profit_factor": self._safe_pf(gross_win, gross_loss),
            "long_wr": sum(r.outcome_status == "WIN" for r in long_rows) / len(long_rows) * 100.0 if long_rows else 0.0,
            "short_wr": sum(r.outcome_status == "WIN" for r in short_rows) / len(short_rows) * 100.0 if short_rows else 0.0,
            "ambiguous": sum(r.outcome_status == "AMBIGUOUS" for r in records),
            "expired": sum(r.outcome_status == "EXPIRED" for r in records),
            "determinate": len(rows),
            "unified_eligible": sum(r.eligibility_status == "UNIFIED_ELIGIBLE" for r in records),
            "conflicts": sum(r.eligibility_status == "CONFLICT" for r in records),
        }

    def execution_diagnostics(self, lab: str | None = None) -> dict:
        """Governed diagnostics over unified learning-ready outcomes."""
        rows = self._learning_rows(lab)
        empty = {"plans": 0, "repaired": 0, "repair_rate": 0.0,
                 "repair_state": "CHƯA CÓ MẪU", "avg_slippage_pct": 0.0,
                 "median_slippage_pct": 0.0, "p90_slippage_pct": 0.0,
                 "slippage_samples": 0, "ambiguous": 0, "expired": 0,
                 "avg_hold_minutes": 0.0}
        if not rows:
            return empty
        repaired = sum("PLAN_REPAIRED" in str(r.setup_tags or "") for r in rows)
        plans = len(rows)
        rate = repaired / plans * 100.0
        state = "CHƯA ĐỦ MẪU" if plans < 20 else ("BÌNH THƯỜNG" if rate < 1 else "THEO DÕI" if rate < 3 else "CẦN KIỂM TRA" if rate < 5 else "CẢNH BÁO GEOMETRY")
        return {**empty, "plans": plans, "repaired": repaired, "repair_rate": rate, "repair_state": state}

    def setup_performance(self, limit: int = 30, lab: str | None = None) -> list[dict]:
        stats = defaultdict(lambda: {"trades": 0, "closed": 0, "wins": 0,
                                     "gross_win": 0.0, "gross_loss": 0.0, "sum_r": 0.0})
        for row in self._learning_rows(lab):
            for tag in [x.strip() for x in str(row.setup_tags or "").split("|") if x.strip()]:
                item = stats[tag]; value = float(row.realized_r or 0.0)
                item["trades"] += 1; item["closed"] += 1; item["sum_r"] += value
                if value > 0: item["wins"] += 1; item["gross_win"] += value
                elif value < 0: item["gross_loss"] += abs(value)
        output=[]
        for setup,item in stats.items():
            closed=item["closed"]
            output.append({"setup":setup,"trades":item["trades"],"closed":closed,
                "win_rate":item["wins"]/closed*100.0 if closed else 0.0,
                "avg_r":item["sum_r"]/closed if closed else 0.0,
                "profit_factor":self._safe_pf(item["gross_win"],item["gross_loss"]),
                "reliable":closed>=self.MIN_SETUP_SAMPLE})
        output.sort(key=lambda x:(1 if x["reliable"] else 0,x["avg_r"],x["closed"]),reverse=True)
        return output[:limit]

    def confidence_calibration(self) -> list[dict]:
        buckets=[(0,50,"0–49"),(50,60,"50–59"),(60,70,"60–69"),(70,80,"70–79"),(80,90,"80–89"),(90,101,"90–100")]
        rows=[(float(r.confidence), float(r.realized_r or 0.0)) for r in self._learning_rows() if r.confidence is not None]
        result=[]
        for low,high,label in buckets:
            selected=[(c,v) for c,v in rows if low<=c<high]; n=len(selected)
            wins=sum(v>0 for _,v in selected); avg=sum(c for c,_ in selected)/n if n else 0.0; observed=wins/n*100.0 if n else 0.0
            result.append({"bucket":label,"samples":n,"avg_confidence":avg,"observed_win_rate":observed,
                           "calibration_gap":observed-avg if n else 0.0,"reliable":n>=self.MIN_CALIBRATION_SAMPLE})
        return result

    def rejection_monitor(self, recent_limit: int = 2000) -> dict:
        if not self.db_path.exists():
            return {
                "evaluations": 0,
                "accepted": 0,
                "acceptance_rate": 0.0,
                "top_rejections": [],
                "strictness": "CHƯA CÓ DỮ LIỆU",
                "recommendation": "Cần thêm lượt quét.",
            }

        with self._connect() as con:
            rows = con.execute("""
                SELECT eligible, rejection_reasons, created_at
                FROM signal_evaluations
                ORDER BY id DESC
                LIMIT ?
            """, (int(recent_limit),)).fetchall()

        total = len(rows)
        accepted = sum(int(row[0] or 0) for row in rows)
        counter = Counter()
        for eligible, reasons, _ in rows:
            if int(eligible or 0):
                continue
            for reason in str(reasons or "").split("|"):
                reason = reason.strip()
                if not reason:
                    continue
                known_micro = {
                    "MICROSTRUCTURE_CONFLICT",
                    "MICRO_LOW_COS",
                    "MICRO_OPPOSING_BIAS",
                    "MICRO_NO_CONFIRMATION",
                    "LOW_ABSORPTION",
                    "LOW_POSITION_BUILDING",
                    "LOW_ORDERFLOW_CONFIRMATION",
                    "MICRO_WALL_UNSTABLE",
                    "MICRO_LOW_WALL_PERSISTENCE",
                    "MICRO_WALL_SPOOFING_RISK",
                    "MICRO_WALL_FAST_REMOVAL",
                }
                if reason in known_micro:
                    counter[reason] += 1
                    counter["MICROSTRUCTURE_REJECTION_TOTAL"] += 1
                else:
                    counter[reason] += 1

        rate = accepted / total * 100.0 if total else 0.0
        if total < 100:
            strictness = "CHƯA ĐỦ MẪU"
            recommendation = "Thu thập ít nhất 100 lượt đánh giá trước khi đổi ngưỡng."
        elif rate == 0:
            strictness = "QUÁ KHẮT KHE"
            recommendation = "Chạy Shadow Threshold; chưa tự hạ ngưỡng chính."
        elif rate < 0.5:
            strictness = "RẤT KHẮT KHE"
            recommendation = "So sánh ngưỡng chính với Shadow trong ít nhất 30 tín hiệu."
        elif rate < 2.0:
            strictness = "KHẮT KHE"
            recommendation = "Giữ ngưỡng chính, tiếp tục theo dõi nguyên nhân loại phổ biến."
        else:
            strictness = "BÌNH THƯỜNG"
            recommendation = "Tần suất tín hiệu đang đủ để đánh giá."

        return {
            "evaluations": total,
            "accepted": accepted,
            "acceptance_rate": rate,
            "top_rejections": counter.most_common(8),
            "strictness": strictness,
            "recommendation": recommendation,
            "microstructure_rejections": {
                key: counter.get(key, 0)
                for key in (
                    "MICROSTRUCTURE_CONFLICT",
                    "MICRO_LOW_COS",
                    "MICRO_OPPOSING_BIAS",
                    "MICRO_NO_CONFIRMATION",
                    "LOW_ABSORPTION",
                    "LOW_POSITION_BUILDING",
                    "LOW_ORDERFLOW_CONFIRMATION",
                    "MICRO_WALL_UNSTABLE",
                    "MICRO_LOW_WALL_PERSISTENCE",
                    "MICRO_WALL_SPOOFING_RISK",
                    "MICRO_WALL_FAST_REMOVAL",
                    "MICROSTRUCTURE_REJECTION_TOTAL",
                )
            },
        }

    def threshold_comparison(self) -> dict:
        if not self.db_path.exists():
            return {
                "main_candidates": 0,
                "shadow_candidates": 0,
                "message": "Chưa có dữ liệu.",
            }

        with self._connect() as con:
            rows = con.execute("""
                SELECT confidence, entry_score, risk_score, rr_planned, entry_ready
                FROM signal_evaluations
                ORDER BY id DESC
                LIMIT 3000
            """).fetchall()

        main = 0
        shadow = 0
        for conf, entry, risk, rr, ready in rows:
            conf = float(conf or 0)
            entry = float(entry or 0)
            risk = float(risk or 0)
            rr = float(rr or 0)
            ready = int(ready or 0)

            if ready and conf >= 68 and entry >= 62 and risk <= 50 and rr >= 1.8:
                main += 1
            if conf >= 45 and entry >= 45 and risk <= 65 and rr >= 1.4:
                shadow += 1

        extra = max(0, shadow - main)
        return {
            "main_candidates": main,
            "shadow_candidates": shadow,
            "extra_shadow": extra,
            "message": (
                f"Discovery Shadow tạo thêm {extra} ứng viên. "
                "MAIN vẫn giữ Quality Gate; Shadow chỉ dùng để thu thập mẫu."
            ),
        }

    def weight_recommendations(self) -> list[dict]:
        """
        Evidence-only recommendations. No automatic mutation of production weights.
        """
        recommendations = []
        for item in self.setup_performance(limit=100, lab="MAIN"):
            if not item["reliable"]:
                continue
            if item["closed"] < 10:
                action = "GIỮ NGUYÊN"
                delta = 0
            elif item["win_rate"] >= 70 and item["avg_r"] >= 0.50:
                action = "ĐỀ XUẤT TĂNG NHẸ"
                delta = +2
            elif item["win_rate"] < 45 or item["avg_r"] < 0:
                action = "ĐỀ XUẤT GIẢM NHẸ"
                delta = -2
            else:
                action = "GIỮ NGUYÊN"
                delta = 0
            recommendations.append({
                "setup": item["setup"],
                "samples": item["closed"],
                "win_rate": item["win_rate"],
                "avg_r": item["avg_r"],
                "action": action,
                "delta": delta,
            })
        return recommendations

    def smart_money_kpis(self) -> dict:
        rows=self._learning_rows(); total=len(rows)
        empty={"closed":0,"early_entry_rate":0.0,"smart_money_alignment_rate":0.0,"strong_footprint_rate":0.0,"position_building_confirm_rate":0.0}
        if not total: return empty
        tags=[str(r.setup_tags or "") for r in rows]
        return {"closed":total,"early_entry_rate":sum("EARLY_ENTRY_HIGH" in t for t in tags)/total*100.0,
                "smart_money_alignment_rate":sum("SMART_MONEY_ALIGNED" in t for t in tags)/total*100.0,
                "strong_footprint_rate":sum("FOOTPRINT_DEPTH_STRONG" in t for t in tags)/total*100.0,
                "position_building_confirm_rate":sum(any(f"POSITION_BUILDING_{v}" in t for v in (50,60,70,80,90,100)) for t in tags)/total*100.0}

    def footprint_lifecycle_matrix(self) -> list[dict]:
        buckets: dict[tuple[str,str,str], list[float]]={}
        for row in self._learning_rows():
            tags=str(row.setup_tags or "").replace(",","|").split("|")
            lifecycle=next((t.replace("LIFECYCLE_","",1) for t in tags if t.startswith("LIFECYCLE_")),"UNKNOWN")
            depth=next((t.replace("FOOTPRINT_DEPTH_","",1) for t in tags if t.startswith("FOOTPRINT_DEPTH_")),"NONE")
            alignment=next((t.replace("SMART_MONEY_","",1) for t in tags if t.startswith("SMART_MONEY_")),"NOT_APPLIED")
            buckets.setdefault((lifecycle,depth,alignment),[]).append(float(row.realized_r or 0.0))
        result=[]
        for (lifecycle,depth,alignment),values in buckets.items():
            result.append({"lifecycle":lifecycle,"confirmation_depth":depth,"alignment":alignment,
                           "samples":len(values),"win_rate":sum(v>0 for v in values)/len(values)*100.0,"avg_r":sum(values)/len(values)})
        result.sort(key=lambda x:(x["samples"],x["avg_r"]),reverse=True)
        return result

